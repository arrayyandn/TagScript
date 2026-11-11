"""Action blocks and the kinds of their arguments.

An action never touches Discord. When it runs it adds one typed item to the plan, and
the caller carries the plan out. Every target is written out in the script, so member
text can't choose a role, channel, emoji, message or command.
"""

from __future__ import annotations

from typing import Any, Callable

from .blocks import Fact, Fail, Spec, literal
from .parse import Block, Sep

__all__ = (
    "Kind",
    "ActionBlock",
    "ROLE",
    "EMOJI",
    "TARGET",
    "DURATION",
    "SNOWFLAKE",
    "COMMAND",
    "id_shaped",
)


def _digits(s: str) -> bool:
    return 0 < len(s) <= 20 and s.isascii() and s.isdigit()


def id_shaped(s: str) -> bool:
    """An id, or a user, channel or role mention."""
    for head in ("<@&", "<@!", "<@", "<#"):
        if s.startswith(head) and s.endswith(">"):
            return _digits(s[len(head) : -1])
    return _digits(s)


class Kind:
    """A written-out argument. ``parse`` returns the plan value or raises ValueError."""

    def __init__(self, name: str, parse: Callable[[str], Any]):
        self.name, self.parse = name, parse

    def compile(self, seq: tuple, err, block: str) -> Any:
        text = literal(seq)
        if text is None:
            inner = next(p for p in seq if isinstance(p, Block))
            err(f"{{{block}}} needs its {self.name} written out. {err.written(inner)} can't give it.", at=inner)
            return None
        try:
            return self.parse(text.strip())
        except ValueError as e:
            err(f"{{{block}}}: {e}")
            return None

    def value(self, data: Any, r) -> Any:
        return data

    def shown(self, data: Any, src: str) -> Any:
        return data


def _role(s: str) -> str:
    inner = s[3:-1] if s.startswith("<@&") and s.endswith(">") else s
    if not _digits(inner):
        raise ValueError(f"{s[:40]!r} isn't a role. Write <@&id> or the id.")
    return inner


EMOJI_RANGES = (
    (0x00A9, 0x00A9),
    (0x00AE, 0x00AE),
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0x2122, 0x2122),
    (0x2139, 0x2139),
    (0x2194, 0x21AA),
    (0x231A, 0x23FF),
    (0x24C2, 0x24C2),
    (0x25AA, 0x25FE),
    (0x2600, 0x27BF),
    (0x2934, 0x2935),
    (0x2B05, 0x2B55),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3299),
    (0x1F000, 0x1FAFF),
)


def _base(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in EMOJI_RANGES) and not 0x1F1E6 <= cp <= 0x1F1FF


def _modifier(cp: int) -> bool:
    """Variation selectors, skin tones and tag characters, which follow a base emoji."""
    return cp in (0xFE0E, 0xFE0F) or 0x1F3FB <= cp <= 0x1F3FF or 0xE0020 <= cp <= 0xE007F


def _unicode_emoji(s: str) -> bool:
    """One emoji: a keycap, a flag, or base emoji with modifiers joined by ZWJ.

    shortcut: the emoji code points are block ranges, not the Unicode emoji list. Element
    re-checks before reacting; use the real list if a wrong emoji gets through.
    """
    if s[:1] in set("0123456789#*"):
        return s[1:] in ("⃣", "️⃣")
    cps = [ord(c) for c in s]
    if len(cps) == 2 and all(0x1F1E6 <= cp <= 0x1F1FF for cp in cps):
        return True
    need_base = True
    for cp in cps:
        if need_base:
            if not _base(cp):
                return False
            need_base = False
        elif cp == 0x200D:
            need_base = True
        elif not _modifier(cp):
            return False
    return not need_base


def _emoji(s: str) -> str:
    if s.startswith("<") and s.endswith(">"):
        bits = s[1:-1].split(":")
        if (
            len(bits) == 3
            and bits[0] in ("", "a")
            and 2 <= len(bits[1]) <= 32
            and all(c.isascii() and (c.isalnum() or c == "_") for c in bits[1])
            and _digits(bits[2])
        ):
            return s
    elif 0 < len(s) <= 16 and _unicode_emoji(s):
        return s
    raise ValueError(f"{s[:40]!r} isn't an emoji. Write the emoji or <:name:id>.")


def _target(s: str) -> str:
    if s.lower() == "dm":
        return "dm"
    inner = s[2:-1] if s.startswith("<#") and s.endswith(">") else s
    if not _digits(inner):
        raise ValueError(f"{s[:40]!r} isn't a channel. Write dm or <#id>.")
    return inner


def _duration(s: str) -> int:
    unit = 60 if s[-1:].lower() == "m" else 1
    num = s[:-1] if s[-1:].lower() in ("s", "m") else s
    if not (0 < len(num) <= 4 and num.isascii() and num.isdigit()):
        raise ValueError(f"{s[:40]!r} isn't a time. Write 10s or 5m.")
    secs = int(num) * unit
    if not 5 <= secs <= 600:
        raise ValueError("The time must be from 5s to 10m.")
    return secs


def _snowflake(s: str) -> str:
    if not _digits(s):
        raise ValueError(f"{s[:40]!r} isn't an id.")
    return s


ROLE = Kind("role", _role)
EMOJI = Kind("emoji", _emoji)
TARGET = Kind("channel", _target)
DURATION = Kind("time", _duration)
SNOWFLAKE = Kind("id", _snowflake)


class _Command(Kind):
    """Fixed text plus id facts, each written directly into the command as its own argument."""

    max_chars = 100

    def __init__(self):
        super().__init__("command", str)

    def compile(self, seq, err, block):
        parts = [p.char if isinstance(p, Sep) else p for p in seq]
        if not parts or not isinstance(parts[0], str) or not parts[0].strip():
            err(f"{{{block}}} needs the command name written out first, like {{c:avatar {{user(id)}}}}.")
            return None
        if sum(len(p) for p in parts if isinstance(p, str)) > self.max_chars:
            err(f"A command can have at most {self.max_chars} characters of text.")
            return None
        for i, p in enumerate(parts):
            if isinstance(p, str):
                continue
            if not (isinstance(p.spec, Fact) and p.spec.is_id(p)):
                err(
                    f"{err.written(p)} can't go in a command. Only fixed text and ids such as "
                    "{user(id)} can, so member text never reaches a command.",
                    at=p,
                )
                return None
            before = parts[i - 1]
            after = parts[i + 1] if i + 1 < len(parts) else " "
            if not (isinstance(before, str) and before[-1:].isspace()) or not (
                isinstance(after, str) and after[:1].isspace()
            ):
                err(f"{err.written(p)} must be its own argument in a command, with spaces around it.", at=p)
                return None
        return tuple(parts)

    def value(self, data, r):
        out = []
        for p in data:
            if isinstance(p, str):
                out.append(p)
                continue
            v = r.text((p,)).strip()
            if not id_shaped(v):
                raise Fail(f"{{{p.name}}} didn't give an id, so the command won't run.")
            out.append(v)
        return "".join(out).strip()

    def shown(self, data, src):
        return "".join(p if isinstance(p, str) else src[p.start : p.end] for p in data).strip()


COMMAND = _Command()


class ActionBlock(Spec):
    """A block that adds one typed item to the plan when it runs, and prints nothing.

    ``kind`` is the item's ``kind``, ``fields`` are fixed fields (``{"op": "add"}``), and
    ``arg`` is the :class:`Kind` read from the param (``where="param"``) or the payload
    into ``field``. With ``replace`` a later block of the same kind replaces the earlier
    item, so the last one on the taken path wins.
    """

    category = "action"

    def __init__(
        self,
        names: tuple[str, ...],
        kind: str,
        *,
        arg: Kind | None = None,
        field: str | None = None,
        where: str = "payload",
        fields: dict | None = None,
        replace: bool = False,
        doc: str = "",
        example: str = "",
        gate: str | None = None,
    ):
        if (arg is None) != (field is None) or where not in ("param", "payload"):
            raise ValueError("arg and field go together; where is 'param' or 'payload'.")
        self.names, self.kind, self.arg, self.field = names, kind, arg, field
        self.where, self.fields, self.replace = where, dict(fields or {}), replace
        self.doc, self.gate = doc, gate
        self.example = example or f"{{{names[0]}}}"

    def compile(self, node, err, engine):
        if self.arg is None:
            self.shape(node, err)
            return None
        on_param = self.where == "param"
        if not self.shape(node, err, param="yes" if on_param else "no", payload="no" if on_param else "yes"):
            return None
        return self.arg.compile(node.param if on_param else node.payload, err, node.name)

    def item(self, node: Block, src: str) -> dict:
        """The item as written, for the checker. A command keeps its id blocks as written."""
        it = {"kind": self.kind, **self.fields}
        if self.arg is not None:
            it[self.field] = self.arg.shown(node.data, src)
        return it

    def value(self, node, r):
        it = {"kind": self.kind, **self.fields}
        if self.arg is not None:
            it[self.field] = self.arg.value(node.data, r)
        r.add(it, self.replace)
        return ""

    def paths(self, node):
        return [], []
