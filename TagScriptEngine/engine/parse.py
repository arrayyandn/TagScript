"""The Engine's parser: one iterative pass that builds an immutable tree with spans.

Structure comes only from the script's own text. ``| ~ ,`` become :class:`Sep` markers,
and a value produced at run time is never parsed again.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable

__all__ = ("Sep", "PIPE", "TILDE", "COMMA", "Block", "Problem", "Tree", "parse", "problem", "capped")

ESCAPABLE = frozenset("{}|:()~,\\")
SPECIAL = frozenset("\\{}()|:~,")


class Sep:
    """An unescaped ``|``, ``~`` or ``,`` written in a block's parameter or payload."""

    __slots__ = ("char",)

    def __init__(self, char: str):
        self.char = char

    def __repr__(self):
        return f"Sep({self.char!r})"


PIPE, TILDE, COMMA = Sep("|"), Sep("~"), Sep(",")
SEPS = {"|": PIPE, "~": TILDE, ",": COMMA}


@dataclass(frozen=True, slots=True, eq=False)
class Block:
    """``{name(param):payload}``. ``param`` and ``payload`` are tuples of str, Sep and Block, or None.
    ``kids`` are the blocks written directly inside it, in order, wherever they sit."""

    name: str
    param: tuple | None
    payload: tuple | None
    start: int
    end: int
    spec: Any = None
    data: Any = None
    kids: tuple = field(default=(), repr=False)  # the blocks are already in param and payload


@dataclass(frozen=True, slots=True)
class Problem:
    message: str
    line: int
    col: int
    start: int
    end: int
    severity: str = "error"

    def to_json(self) -> dict:
        return {
            "message": self.message,
            "line": self.line,
            "col": self.col,
            "start": self.start,
            "end": self.end,
            "severity": self.severity,
        }


def position(src: str, offset: int) -> tuple[int, int]:
    """1-based line and column of an offset."""
    return src.count("\n", 0, offset) + 1, offset - (src.rfind("\n", 0, offset) + 1) + 1


def problem(src: str, message: str, start: int, end: int, severity: str = "error") -> Problem:
    line, col = position(src, start)
    return Problem(message, line, col, start, end, severity)


@dataclass(frozen=True, slots=True)
class Tree:
    """``engine`` is the Engine that parsed it. Another Engine won't run it."""

    src: str
    root: tuple
    problems: tuple[Problem, ...]
    blocks: tuple[Block, ...]
    depth: int
    engine: Any = field(default=None, repr=False, compare=False)

    @property
    def ok(self) -> bool:
        return not any(p.severity == "error" for p in self.problems)


MORE = "…and more problems. Fix these first."


def capped(problems, cap: int) -> tuple[Problem, ...]:
    """Sorted, at most ``cap`` problems, then one that says there are more."""
    more = any(p.message == MORE for p in problems)
    shown = sorted((p for p in problems if p.message != MORE), key=lambda p: p.start)
    if len(shown) > cap:
        more, shown = True, shown[:cap]
    if more and shown:
        last = shown[-1]
        shown.append(Problem(MORE, last.line, last.col, last.start, last.end))
    return tuple(shown)


NAME, PARAM, AFTER, PAYLOAD, ROOT = range(5)


class _Frame:
    __slots__ = ("state", "start", "name", "name_ok", "param", "payload", "cur", "buf", "parens", "kids", "bad")

    def __init__(self, state: int, start: int):
        self.state = state
        self.start = start
        self.name = ""
        self.name_ok = True
        self.param = None
        self.payload = None
        self.cur: list = []
        self.buf: list[str] = []
        self.parens = 0
        self.kids: list = []
        self.bad = False  # a broken shape the parser found, such as text after )

    def flush(self):
        if self.buf:
            self.cur.append("".join(self.buf))
            self.buf.clear()

    def take_name(self):
        self.name = "".join(self.buf)
        self.buf.clear()
        self.cur = []


Bind = Callable[[str, bool, "tuple | None", "tuple | None", int, int, list, tuple, bool], Block]


def parse(
    src: str, *, chars: int, blocks: int, depth: int, max_problems: int, bind: Bind, loose: bool = False
) -> Tree:
    """Scan ``src`` without recursion. ``bind`` turns each closed block into a node.

    The scan stops once there are more than ``max_problems`` problems. With ``loose``, brace and
    shape problems are warnings, and a ``{`` that is never closed is text, as legacy prints it.
    """
    stray: list[Problem] = []
    literal: frozenset = frozenset()
    while True:
        tree, unclosed = _scan(src, chars, blocks, depth, max_problems, bind, loose, literal)
        if not (loose and unclosed):
            return replace(tree, problems=tuple(sorted((*stray, *tree.problems), key=lambda p: p.start)))
        # Taking out a { that no } closes leaves every other pair as it was, so this loops once at most.
        literal |= {f.start for f in unclosed}
        stray += [_unclosed(src, f, "warning") for f in unclosed]


def _unclosed(src: str, frame: "_Frame", severity: str) -> Problem:
    return problem(src, f"Missing }} to close {{{_shown(frame)}.", frame.start, frame.start + 1, severity)


def _scan(src, chars, blocks, depth, max_problems, bind, loose, literal):
    soft = "warning" if loose else "error"
    problems: list[Problem] = []
    if len(src) > chars:
        problems.append(problem(src, f"This script is over {chars:,} characters.", 0, len(src)))
        return Tree(src, (), tuple(problems), (), 0), ()

    stack = [_Frame(ROOT, 0)]
    nodes: list[Block] = []
    opened = 0
    deepest = 0
    i, n = 0, len(src)
    while i < n:
        if len(problems) > max_problems:
            return Tree(src, (), tuple(problems), (), deepest), ()
        c = src[i]
        top = stack[-1]
        if c not in SPECIAL or (c == "{" and i in literal):
            j = i + 1
            while j < n and src[j] not in SPECIAL:
                j += 1
            if top.state == AFTER:
                problems.append(problem(src, "Expected : or } after ).", i, j, soft))
                top.bad = True
            else:
                top.buf.append(src[i:j])
            i = j
            continue
        if c == "\\":
            nxt = src[i + 1 : i + 2]
            if nxt in ESCAPABLE and nxt:
                top.buf.append(nxt)
                i += 2
            else:
                top.buf.append(c)
                i += 1
            continue
        if c == "{":
            opened += 1
            if opened > blocks:
                problems.append(problem(src, f"This script has more than {blocks:,} blocks.", i, i + 1))
                return Tree(src, (), tuple(problems), (), deepest), ()
            if len(stack) > depth:
                problems.append(problem(src, f"Blocks are nested more than {depth} deep.", i, i + 1))
                return Tree(src, (), tuple(problems), (), deepest), ()
            if top.state == NAME:
                top.name_ok = False
            elif top.state == AFTER:
                problems.append(problem(src, "Expected : or } after ).", i, i + 1, soft))
                top.bad = True
            else:
                top.flush()
            stack.append(_Frame(NAME, i))
            deepest = max(deepest, len(stack) - 1)
            i += 1
            continue
        if c == "}":
            if top.state == ROOT:
                problems.append(problem(src, "Unmatched }. Type \\} for a brace.", i, i + 1, soft))
                top.buf.append(c)
                i += 1
                continue
            node = _close(src, top, i + 1, problems, bind, soft)
            stack.pop()
            parent = stack[-1]
            parent.kids.append(node)
            if parent.state != NAME:
                parent.flush()
                parent.cur.append(node)
            nodes.append(node)
            i += 1
            continue
        # c is one of ( ) : | ~ ,
        st = top.state
        if st == NAME:
            if c == "(":
                top.take_name()
                top.state, top.parens = PARAM, 1
                top.param = top.cur
            elif c == ":":
                top.take_name()
                top.state = PAYLOAD
                top.payload = top.cur
            else:
                top.buf.append(c)
        elif st == PARAM:
            if c == "(":
                top.parens += 1
                top.buf.append(c)
            elif c == ")":
                top.parens -= 1
                if top.parens:
                    top.buf.append(c)
                else:
                    top.flush()
                    top.state = AFTER
            elif c == ":":
                top.buf.append(c)
            else:
                top.flush()
                top.cur.append(SEPS[c])
        elif st == AFTER:
            if c == ":":
                top.state = PAYLOAD
                top.cur = top.payload = []
            else:
                problems.append(problem(src, "Expected : or } after ).", i, i + 1, soft))
                top.bad = True
        elif st == PAYLOAD and c in SEPS:
            top.flush()
            top.cur.append(SEPS[c])
        else:
            top.buf.append(c)
        i += 1

    unclosed = stack[1:]
    if not loose:
        problems.extend(_unclosed(src, frame, "error") for frame in unclosed)
    root = stack[0]
    root.flush()
    problems.sort(key=lambda p: p.start)
    return Tree(src, tuple(root.cur), tuple(problems), tuple(nodes), deepest), unclosed


def _shown(frame: _Frame) -> str:
    name = frame.name if frame.state != NAME else "".join(frame.buf)
    return name[:32]


def _close(src: str, frame: _Frame, end: int, problems: list, bind: Bind, soft: str) -> Block:
    if frame.state == NAME:
        frame.take_name()
    else:
        frame.flush()
    if frame.state == PARAM:
        problems.append(problem(src, f"Missing ) in {{{frame.name[:32]}(.", frame.start, end, soft))
        frame.bad = True
    param = tuple(frame.param) if frame.param is not None else None
    payload = tuple(frame.payload) if frame.payload is not None else None
    kids = tuple(frame.kids)
    return bind(frame.name, frame.name_ok, param, payload, frame.start, end, problems, kids, frame.bad)
