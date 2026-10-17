import math
import time
from typing import Any, Optional

from discord.ext.commands import CooldownMapping

from ..exceptions import CooldownExceeded
from ..interface import verb_required_block
from ..interpreter import Context
from .helpers import helper_split

__all__ = ("CooldownBlock",)


class CooldownBlock(verb_required_block(True, payload=True, parameter=True)):
    """
    The cooldown block implements cooldowns when running a tag.
    The parameter requires 2 values to be passed: ``rate`` and ``per`` integers.
    The ``rate`` is the number of times the tag can be used every ``per`` seconds.

    The payload requires a ``key`` value, which is the key used to store the cooldown.
    A key should be any string that is unique. If a channel's ID is passed as a key,
    the tag's cooldown will be enforced on that channel. Running the tag in a separate channel
    would have a different cooldown with the same ``rate`` and ``per`` values.

    The payload also has an optional ``message`` value, which is the message to be sent when the
    cooldown is exceeded. If no message is passed, the default message will be sent instead.
    The cooldown message supports 2 blocks: ``key`` and ``retry_after``.

    **Usage:** ``{cooldown(<rate>|<per>):<key>|[message]}``

    **Payload:** key, message

    **Parameter:** rate, per

    **Examples:** ::

        {cooldown(1|10):{author(id)}}
        # the tag author used the tag more than once in 10 seconds
        # The bucket for 741074175875088424 has reached its cooldown. Retry in 3.25 seconds."

        {cooldown(3|3):{channel(id)}|Slow down! This tag can only be used 3 times per 3 seconds per channel. Try again in **{retry_after}** seconds."}
        # the tag was used more than 3 times in 3 seconds in a channel
        # Slow down! This tag can only be used 3 times per 3 seconds per channel. Try again in **0.74** seconds.

    **Deferred mode**

    By default the buckets live in memory on the class and the block raises
    :class:`~TagScriptEngine.exceptions.CooldownExceeded` as soon as one is exceeded.
    That breaks when the interpreter runs in several processes or restarts, so passing
    ``defer=True`` moves the check to whoever consumes the
    :class:`~TagScriptEngine.interpreter.Response`.

    A deferred block never raises, never touches the in-memory buckets and always outputs an
    empty string. Instead it appends one dict per evaluated block, in script order, to
    ``response.actions["cooldowns"]``::

        {
            "key": str,              # the interpreted key
            "rate": int,             # uses allowed, at least 1
            "per": float,            # window in seconds, greater than 0
            "message": str | None,   # custom message, or None for the default one
        }

    ``message`` already has ``{key}`` filled in, while the literal text ``{retry_after}`` is
    left for the consumer to replace. When it is ``None`` the consumer should send the default
    message, ``The bucket for {key} has reached its cooldown. Retry in {retry_after} seconds.``,
    filling in both itself.
    Every value is a plain JSON type, so the actions can be sent over HTTP as they are.

    In deferred mode ``rate`` must be a whole number and ``per`` may be a decimal (the legacy
    mode parses ``rate`` as a decimal and ``per`` as a whole number). Invalid parameters make the
    block do nothing, like in the legacy mode.

    The consumer should check the entries in order against its shared storage, scoping each
    bucket by its own cooldown key (the ``cooldown_key`` keyword passed to the interpreter) plus
    the entry's ``key``. The first exceeded entry wins: send only its message and ignore the body
    and every other action. This differs slightly from the legacy mode, which keeps any text
    output before the block and drops everything after it. Since the script runs to the end
    before any check, a script that errors after a cooldown block also no longer uses up a use.

    Parameters
    ----------
    defer: bool
        Whether to leave the cooldown check to the consumer through
        ``response.actions["cooldowns"]`` instead of raising. Defaults to ``False``.
    """

    ACCEPTED_NAMES = ("cooldown",)
    COOLDOWNS: dict[Any, CooldownMapping] = {}

    def __init__(self, *, defer: bool = False):
        self.defer = defer

    @classmethod
    def create_cooldown(cls, key: Any, rate: int, per: int) -> CooldownMapping:
        cooldown = CooldownMapping.from_cooldown(rate, per, lambda x: x)
        cls.COOLDOWNS[key] = cooldown
        return cooldown

    def process(self, ctx: Context) -> Optional[str]:
        verb = ctx.verb
        try:
            rate, per = helper_split(verb.parameter, maxsplit=1)
            if self.defer:
                rate = int(rate)
                per = float(per)
            else:
                per = int(per)
                rate = float(rate)
        except (ValueError, TypeError):
            return
        if self.defer and (rate < 1 or not (math.isfinite(per) and per > 0)):
            return

        if split := helper_split(verb.payload, False, maxsplit=1):
            key, message = split
        else:
            key = verb.payload
            message = None

        if self.defer:
            return self._defer(ctx, key, rate, per, message)

        cooldown_key = ctx.response.extra_kwargs.get("cooldown_key")
        if cooldown_key is None:
            cooldown_key = ctx.original_message
        try:
            cooldown = self.COOLDOWNS[cooldown_key]
            base = cooldown._cooldown
            if (rate, per) != (base.rate, base.per):
                cooldown = self.create_cooldown(cooldown_key, rate, per)
        except KeyError:
            cooldown = self.create_cooldown(cooldown_key, rate, per)

        current = time.time()
        bucket = cooldown.get_bucket(key, current)
        retry_after = bucket.update_rate_limit(current)
        if retry_after:
            retry_after = round(retry_after, 2)
            if message:
                message = message.replace("{key}", str(key)).replace(
                    "{retry_after}", str(retry_after)
                )
            else:
                message = f"The bucket for {key} has reached its cooldown. Retry in {retry_after} seconds."
            raise CooldownExceeded(message, bucket, key, retry_after)
        return ""

    @staticmethod
    def _defer(ctx: Context, key: str, rate: int, per: float, message: Optional[str]) -> str:
        ctx.response.actions.setdefault("cooldowns", []).append(
            {
                "key": key,
                "rate": rate,
                "per": per,
                "message": message.replace("{key}", key) if message else None,
            }
        )
        return ""
