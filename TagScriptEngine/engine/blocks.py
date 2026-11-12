"""Block specs. A spec says how a block is written, checked and run.

``compile`` runs once at parse time and stores what it needs in ``Block.data``. ``value``
runs the block and returns its text. A control block sets ``branches`` and implements
``choose``, which picks the one part that runs.
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote, quote_plus

from .math import MathError, compile_math, evaluate, format_number, to_number
from .parse import COMMA, PIPE, TILDE, Block, Sep

__all__ = (
    "Spec",
    "Fact",
    "Fail",
    "Budget",
    "StopRun",
    "BreakRun",
    "literal",
    "split",
    "BUILTINS",
    "DEFAULT_HINTS",
)


class Fail(Exception):
    """The run ends with ``script_error``. The message is shown in the tester."""


class Budget(Exception):
    """The run ends with ``script_budget``."""


class StopRun(Exception):
    def __init__(self, text: str):
        self.text = text


class BreakRun(Exception):
    pass


def literal(seq: tuple | None) -> str | None:
    """The text of ``seq`` if it has no blocks in it, else None."""
    if seq is None:
        return None
    out = []
    for part in seq:
        if isinstance(part, Block):
            return None
        out.append(part.char if isinstance(part, Sep) else part)
    return "".join(out)


def find(seqs, cls) -> Block | None:
    """The first block whose spec is a ``cls``, anywhere inside ``seqs``."""
    todo = [s for s in seqs if s]
    while todo:
        for part in todo.pop():
            if part.__class__ is Block:
                if isinstance(part.spec, cls):
                    return part
                todo.extend(s for s in (part.param, part.payload) if s)
    return None


def split(seq: tuple, sep: Sep, limit: int = -1) -> list[tuple]:
    parts: list[tuple] = []
    start = 0
    for i, part in enumerate(seq):
        if part is sep and limit != 0:
            parts.append(seq[start:i])
            start = i + 1
            limit -= 1
    parts.append(seq[start:])
    return parts


class Spec:
    """Base for every block. Subclasses set ``names`` and override what they need."""

    names: tuple[str, ...] = ()
    doc = ""
    example = ""
    gate: str | None = None
    category = "text"
    cost = 1
    branches = False

    def compile(self, node: Block, err: Callable[[str], None], engine) -> Any:
        return None

    def value(self, node: Block, r) -> str:
        return ""

    def choose(self, node: Block, r) -> tuple[tuple | None, str]:
        return None, ""

    def paths(self, node: Block) -> tuple[list[tuple], list[tuple]]:
        """The parts that always run, and the alternatives of which at most one runs."""
        return [s for s in (node.param, node.payload) if s], []

    def check(self, node: Block, ctx) -> list[str]:
        """Extra save problems. ``ctx`` is whatever the caller passed to ``Engine.check``."""
        return []

    def shape(self, node: Block, err, *, param: str = "no", payload: str = "no") -> bool:
        """Check the written form. Each rule is "no", "yes" or "opt"."""
        for rule, seq in ((param, node.param), (payload, node.payload)):
            if (rule == "no" and seq is not None) or (rule == "yes" and not seq):
                err(f"{{{node.name}}} is written like {self.example}.")
                return False
        return True


OPS = ("!=", "==", ">=", "<=", ">", "<")


def compile_cond(seq: tuple) -> tuple:
    """Find the operator in the script's own text only. Blocks are never searched."""
    for op in OPS:
        for i, part in enumerate(seq):
            if part.__class__ is str and op in part:
                k = part.index(op)
                left = seq[:i] + ((part[:k],) if k else ())
                rest = part[k + len(op) :]
                right = ((rest,) if rest else ()) + seq[i + 1 :]
                return op, left, right
    return None, seq, None


def test(cond: tuple, r) -> bool:
    """``<``, ``>``, ``<=`` and ``>=`` on a side that isn't a number end the run, like {math} does.
    Each condition costs a step, even an empty one."""
    r.spend(1)
    op, left, right = cond
    a = r.text(left)
    if op is None:
        return a.strip().lower() == "true"
    b = r.text(right)
    if op == "==":
        return a.strip() == b.strip()
    if op == "!=":
        return a.strip() != b.strip()
    try:
        x, y = to_number(a), to_number(b)
    except MathError:
        a, b = a.strip()[:40], b.strip()[:40]
        raise Fail(f"Can't compare {a!r} with {b!r}: both sides of {op} must be numbers.") from None
    if op == ">=":
        return x >= y
    if op == "<=":
        return x <= y
    return x > y if op == ">" else x < y


def _arms(spec: Spec, node: Block, err) -> list[tuple] | None:
    arms = split(node.payload, PIPE)
    if len(arms) > 2:
        err(f"{{{node.name}}} takes at most two branches, like {spec.example}. Type \\| for a bar.")
        return None
    return arms


class If(Spec):
    names = ("if",)
    doc = "Runs the first branch if the condition is true, else the second."
    example = "{if({user(id)}==111):yes|no}"
    category = "control"
    branches = True

    def compile(self, node, err, engine):
        if not self.shape(node, err, param="yes", payload="yes"):
            return None
        arms = _arms(self, node, err)
        return arms and (compile_cond(node.param), arms)

    def choose(self, node, r):
        cond, arms = node.data
        if test(cond, r):
            return arms[0], "true"
        return (arms[1] if len(arms) > 1 else None), "false"

    def paths(self, node):
        return [node.param], list(node.data[1]) + [()] if node.data else []


class AnyAll(Spec):
    category = "control"
    branches = True

    def __init__(self, names: tuple[str, ...], every: bool):
        self.names, self.every = names, every
        word = "all" if every else "any"
        self.doc = f"Runs the first branch if {word} of the |-separated conditions are true."
        self.example = f"{{{names[0]}(a==a|b==c):yes|no}}"

    def compile(self, node, err, engine):
        if not self.shape(node, err, param="yes", payload="yes"):
            return None
        arms = _arms(self, node, err)
        return arms and (tuple(compile_cond(c) for c in split(node.param, PIPE)), arms)

    def choose(self, node, r):
        conds, arms = node.data
        hit = (all if self.every else any)(test(c, r) for c in conds)
        if hit:
            return arms[0], "true"
        return (arms[1] if len(arms) > 1 else None), "false"

    paths = If.paths


class Random(Spec):
    names = ("random",)
    doc = "Runs one of the options, picked at random. Separate options with ~ or ,."
    example = "{random:Hi~Hey~Hello}"
    category = "control"
    branches = True

    def compile(self, node, err, engine):
        if not self.shape(node, err, payload="yes"):
            return None
        sep = TILDE if any(p is TILDE for p in node.payload) else COMMA
        return split(node.payload, sep)

    def choose(self, node, r):
        i = r.rng.randrange(len(node.data))
        return node.data[i], f"option {i + 1}"

    def paths(self, node):
        return [], list(node.data or ())


class Assign(Spec):
    names = ("=", "let", "assign")
    doc = "Stores text in a variable. Read it back with {name}."
    example = "{=(greeting):Hello}"

    def compile(self, node, err, engine):
        if not self.shape(node, err, param="yes", payload="opt"):
            return None
        name = literal(node.param)
        if name is None:
            err("Variable names must be written out, like {=(name):value}.")
            return None
        name = name.strip()
        if not valid_var(name):
            err(f"{name[:32]!r} can't be a variable name. Use letters, numbers, _ and -.")
            return None
        if name.lower() in engine.specs:
            err(f"{{{name}}} is a block, so it can't be a variable name.")
            return None
        return name.lower()

    def value(self, node, r):
        r.vars[node.data] = r.text(node.payload)
        return ""


def valid_var(name: str) -> bool:
    return 0 < len(name) <= 32 and name.isascii() and all(c.isalnum() or c in "_-" for c in name)


class VarRead(Spec):
    category = "variable"

    def compile(self, node, err, engine):
        return node.name.strip().lower()

    def value(self, node, r):
        return r.vars.get(node.data, "")


VAR = VarRead()


class Math(Spec):
    names = ("math",)
    doc = "Works out a sum. Blocks inside must give a number. Whole numbers print as 2."
    example = "{math:2*(3+4)}"

    def compile(self, node, err, engine):
        if not self.shape(node, err, payload="yes"):
            return None
        lim = engine.limits
        return compile_math(node.payload, err, chars=lim.math_chars, depth=lim.math_depth)

    def value(self, node, r):
        try:
            x = evaluate(node.data, lambda b: to_number(r.text((b,))), r.spend)
        except MathError as e:
            raise Fail(str(e)) from None
        return format_number(x)


class Replace(Spec):
    names = ("replace",)
    doc = "Replaces every old with new in the text."
    example = "{replace(old,new):text}"

    def compile(self, node, err, engine):
        if not self.shape(node, err, param="yes", payload="yes"):
            return None
        parts = split(node.param, COMMA, 1)
        if len(parts) != 2:
            err(f"{{replace}} is written like {self.example}. Type \\, for a comma.")
            return None
        return parts

    def value(self, node, r):
        old, new = r.text(node.data[0]), r.text(node.data[1])
        text = r.text(node.payload)
        size = len(text) + text.count(old) * (len(new) - len(old))
        if size > r.limits.value:
            raise Budget(f"{{replace}} would make {size:,} characters.")
        return text.replace(old, new)


class Case(Spec):
    def __init__(self, name: str, fn: Callable[[str], str]):
        self.names, self.fn = (name,), fn
        self.doc = f"Makes the text {name}case."
        self.example = f"{{{name}:Text}}"

    def compile(self, node, err, engine):
        self.shape(node, err, payload="yes")

    def value(self, node, r):
        return self.fn(r.text(node.payload))


class UrlEncode(Spec):
    names = ("urlencode",)
    doc = "Encodes text for a link. {urlencode(+):…} writes spaces as +."
    example = "{urlencode:two words}"

    def compile(self, node, err, engine):
        if not self.shape(node, err, param="opt", payload="yes"):
            return None
        if node.param is not None and literal(node.param) != "+":
            err("{urlencode} only takes (+).")
        return node.param is not None

    def value(self, node, r):
        return (quote_plus if node.data else quote)(r.text(node.payload))


class Search(Spec):
    """{in}, {contains} and {index}: legacy's PythonBlock, with the same answers."""

    def __init__(self, name: str, doc: str, example: str, fn: Callable[[str, str], str]):
        self.names, self.doc, self.example, self.fn = (name,), doc, example, fn

    def compile(self, node, err, engine):
        self.shape(node, err, param="yes", payload="yes")

    def value(self, node, r):
        return self.fn(r.text(node.param), r.text(node.payload))


def _index(x: str, text: str) -> str:
    words = text.split()
    return str(words.index(x)) if x in words else "-1"


def _bounds(p: str) -> tuple[int, int | None]:
    """(start) or (start-end), each cut to a whole number like legacy. - is the separator, so no negatives."""
    try:
        nums = [int(to_number(s)) for s in p.split("-")]
    except MathError:
        nums = []
    if not 1 <= len(nums) <= 2:
        raise ValueError(f"{{substr}} takes (start) or (start-end), with numbers of 0 or more, not {p[:40]!r}.")
    return nums[0], nums[1] if len(nums) == 2 else None


class Substr(Spec):
    names = ("substr",)
    doc = "The part of the text from start up to end, counting from 0. {substr(2):…} goes to the end."
    example = "{substr(2-5):text}"

    def compile(self, node, err, engine):
        if not self.shape(node, err, param="yes", payload="yes"):
            return None
        p = literal(node.param)
        if p is None:
            return None  # read when the script runs
        try:
            return _bounds(p)
        except ValueError as e:
            err(str(e))

    def value(self, node, r):
        try:
            start, end = node.data or _bounds(r.text(node.param))
        except ValueError as e:
            raise Fail(str(e)) from None
        return r.text(node.payload)[start:end]


def _cond(spec: Spec, node: Block, err) -> tuple | None:
    if node.param is not None and not node.param:
        err(f"{{{node.name}}} is written like {spec.example}.")
    return compile_cond(node.param) if node.param else None


class Stop(Spec):
    names = ("stop",)
    doc = "Ends the script and drops every planned action, {redirect} too, so only its text is posted, in the channel."
    example = "{stop({hasrole(<@&111>)}):You're already verified.}"
    category = "control"

    def compile(self, node, err, engine):
        if not self.shape(node, err, param="opt", payload="opt"):
            return None
        inner = find((node.param, node.payload), Break)
        if inner is not None:
            err("{break} can't go inside {stop}, because the stop must always win.", at=inner)
            return None
        return _cond(self, node, err)

    def value(self, node, r):
        if node.data is None or test(node.data, r):
            raise StopRun(r.text(node.payload))
        return ""


class Break(Spec):
    names = ("break",)
    doc = "Ends the script and keeps the reply and actions so far."
    example = "{break({user(id)}==111)}"
    category = "control"

    def compile(self, node, err, engine):
        if node.payload is not None:
            err("{break} keeps the reply so far and takes no text. To reply with only some text, use {stop(...):text}.")
            return None
        if self.shape(node, err, param="opt"):
            return _cond(self, node, err)

    def value(self, node, r):
        if node.data is None or test(node.data, r):
            raise BreakRun()
        return ""


class Fact(Spec):
    """Reads plain data that the caller passes to ``Engine.run``.

    ``params`` is None for ``{name}``, a tuple of the allowed ``(param)`` words, or a
    :class:`~TagScriptEngine.engine.plan.Kind` for a written-out target such as a role.
    ``ids`` names the params whose value is an id, which may go into a command.
    By default ``{user(id)}`` reads ``facts["user"]["id"]`` and ``{trigger}`` reads
    ``facts["trigger"]``.
    """

    category = "fact"

    def __init__(
        self,
        names: tuple[str, ...],
        *,
        params=None,
        ids: tuple[str, ...] = (),
        read: Callable[[dict, Any], Any] | None = None,
        doc: str = "",
        example: str = "",
        gate: str | None = None,
    ):
        self.names, self.params, self.ids = names, params, ids
        self.read = read or self._lookup
        self.doc, self.gate = doc, gate
        self.example = example or (f"{{{names[0]}({params[0]})}}" if isinstance(params, tuple) else f"{{{names[0]}}}")

    def _lookup(self, facts: dict, param):
        v = facts.get(self.names[0])
        return v.get(param) if param is not None and isinstance(v, dict) else v

    def compile(self, node, err, engine):
        if self.params is None:
            self.shape(node, err)
            return None
        if not self.shape(node, err, param="yes"):
            return None
        p = literal(node.param)
        if p is None:
            err(f"Write the part in () out, like {self.example}.")
            return None
        if isinstance(self.params, tuple):
            p = p.strip().lower()
            if p not in self.params:
                err(f"{{{node.name}}} takes one of: {', '.join(self.params)}.")
            return p
        return self.params.compile(node.param, err, node.name)

    def is_id(self, node: Block) -> bool:
        return isinstance(self.params, tuple) and node.data in self.ids

    def value(self, node, r):
        v = self.read(r.facts, node.data)
        return "" if v is None else str(v)


BUILTINS: tuple[Spec, ...] = (
    Assign(),
    If(),
    AnyAll(("any",), False),
    AnyAll(("all",), True),
    Random(),
    Math(),
    Replace(),
    Case("upper", str.upper),
    Case("lower", str.lower),
    UrlEncode(),
    Search("in", "true if x is anywhere in the text, else false.", "{in(x):text}", lambda x, t: str(x in t).lower()),
    Search(
        "contains",
        "true if x is one of the text's words, split at spaces, else false.",
        "{contains(x):text}",
        lambda x, t: str(x in t.split()).lower(),
    ),
    Search("index", "Which word of the text x is, counting from 0, or -1.", "{index(x):text}", _index),
    Substr(),
    Stop(),
    Break(),
)

_WHO = "Who can use a trigger is a trigger setting."
_FIFTY = "Use {random:text~} instead."
DEFAULT_HINTS = {
    "cooldown": "Cooldowns are a trigger setting.",
    "require": _WHO,
    "whitelist": _WHO,
    "blacklist": _WHO,
    "override": "Commands always run with the member's own permissions.",
    "embed": "Send a saved message with {message:<id>} instead.",
    "silent": "Commands from a script are already quiet.",
    "halt": "Use {stop} instead.",
    "error": "Use {stop} instead.",
    "short": "Use {break} instead.",
    "shortcircuit": "Use {break} instead.",
    "5050": _FIFTY,
    "50": _FIFTY,
    "?": _FIFTY,
    "substring": "Use {substr} instead.",
    "strf": "There's no date or time formatting.",
    "unix": "There's no date or time formatting.",
    "range": "Write the options out in {random:a~b~c} instead.",
    "rangef": "Write the options out in {random:a~b~c} instead.",
    "var": "Use {=(name):value} instead.",
    "m": "Use {math} instead.",
    "calc": "Use {math} instead.",
    "+": "Use {math} instead.",
    "or": "Use {any} instead.",
    "and": "Use {all} instead.",
    "#": "Use {random} instead.",
    "rand": "Use {random} instead.",
}
