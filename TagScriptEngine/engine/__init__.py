"""The Engine: an opt-in TagScript evaluator that parses once and runs only the branch it takes.

It sits beside the legacy :class:`~TagScriptEngine.Interpreter`, which it never touches.

>>> engine = Engine()
>>> tree = engine.parse("{=(a):yes|no}{if(1==1):{a}}")
>>> engine.run(tree, {}).body
'yes|no'
"""

from __future__ import annotations

import difflib
import random
from dataclasses import replace

from .blocks import BUILTINS, DEFAULT_HINTS, VAR, WRITTEN, Assign, Fact, Spec, valid_var
from .check import Action, Report, check
from .parse import Block, Problem, Tree, capped, parse, problem
from .plan import COMMAND, DURATION, EMOJI, ROLE, SNOWFLAKE, TARGET, ActionBlock, Kind
from .run import Limits, Result, Run, TraceStep

__all__ = (
    "Engine",
    "BUILTINS",
    "Spec",
    "Fact",
    "ActionBlock",
    "Kind",
    "ROLE",
    "EMOJI",
    "TARGET",
    "DURATION",
    "SNOWFLAKE",
    "COMMAND",
    "Limits",
    "Tree",
    "Block",
    "Problem",
    "Report",
    "Action",
    "Result",
    "TraceStep",
)


class Engine:
    """Holds a vocabulary and the limits. Safe to share between threads once set up.

    ``blocks`` are extra specs (facts and actions) on top of the text and control blocks.
    ``hints`` maps a name that isn't in the Engine to what to use instead. ``builtins`` are the
    text and control blocks to start from, all of :data:`BUILTINS` by default.

    The legacy options, all off by default, make old scripts print as the legacy Interpreter does:

    - ``loose``: unknown names, unset variables, hinted names, stray braces and blocks of the
      wrong shape print as written, with a warning instead of an error. Names match like legacy:
      facts and variables by their exact case, other blocks in any case, and never with spaces.
    - ``legacy_stop``: ``{stop}`` keeps the text and actions before it, and needs its ``(...)``.
    - ``legacy_break``: ``{break(...):text}`` makes ``text`` the reply and the run goes on.
    - ``shadow_facts``: ``{=(args):...}`` makes ``{args}`` read the variable. Only facts can be
      shadowed, and a shadowed fact can't go in a command.
    """

    def __init__(
        self,
        blocks=(),
        *,
        limits: Limits | None = None,
        hints: dict | None = None,
        builtins=BUILTINS,
        loose: bool = False,
        legacy_stop: bool = False,
        legacy_break: bool = False,
        shadow_facts: bool = False,
    ):
        self.limits = limits or Limits()
        self.hints = {**DEFAULT_HINTS, **(hints or {})}
        self.loose, self.legacy_stop, self.legacy_break = loose, legacy_stop, legacy_break
        self.shadow_facts = shadow_facts
        self.specs: dict[str, Spec] = {}
        self.register(*builtins, *blocks)

    def register(self, *specs: Spec) -> None:
        for spec in specs:
            if not isinstance(spec, Spec) or not spec.names:
                raise TypeError(f"{spec!r} isn't a block spec with names.")
            for name in spec.names:
                key = name.lower()
                if key in self.specs:
                    raise ValueError(f"{{{name}}} is already registered.")
                self.specs[key] = spec

    def parse(self, src: str) -> Tree:
        lim = self.limits
        tree = parse(
            src,
            chars=lim.chars,
            blocks=lim.blocks,
            depth=lim.depth,
            max_problems=lim.problems,
            bind=self._binder(src),
            loose=self.loose,
        )
        assigned = {n.data for n in tree.blocks if isinstance(n.spec, Assign) and n.data}
        unknown = self._unknown(assigned)
        severity = "warning" if self.loose else "error"
        problems = list(tree.problems)
        for n in tree.blocks:
            if len(problems) > lim.problems:
                break
            if (n.spec is VAR and n.data not in assigned) or n.data is UNKNOWN:
                problems.append(problem(src, unknown(n), n.start, n.end, severity))
            elif self.shadow_facts and isinstance(n.spec, ActionBlock) and isinstance(n.data, tuple):
                for p in n.data:
                    if p.__class__ is Block and isinstance(p.spec, Fact) and self.var_key(p.name) in assigned:
                        msg = f"{{{p.name.strip()}}} is set as a variable here, so it can't go in a command."
                        problems.append(problem(src, msg, p.start, p.end))
        return replace(tree, problems=capped(problems, lim.problems), engine=self)

    def var_key(self, name: str) -> str:
        """How a variable is stored: exact in loose mode, like legacy, else in lower case."""
        return name.strip() if self.loose else name.strip().lower()

    def lookup(self, name: str) -> Spec | None:
        """The block ``{name}`` is. Loose mode matches like legacy: a fact by its exact name,
        anything else in any case, and a name with spaces around it is nothing."""
        if not self.loose:
            return self.specs.get(name.strip().lower())
        spec = self.specs.get(name.lower())
        return None if isinstance(spec, Fact) and name not in spec.names else spec

    def check(self, tree: Tree, ctx=None) -> Report:
        """``ctx`` is passed to each spec's ``check`` hook, for the caller's own rules."""
        return check(tree, ctx, self.limits)

    def run(
        self, tree: Tree | str, facts: dict, *, trace: bool = False, rng: random.Random | None = None
    ) -> Result:
        """Run one tree with plain-data ``facts``. Never raises for a script's own problems."""
        if isinstance(tree, str):
            tree = self.parse(tree)
        if tree.engine is not self:
            return Result("", (), False, 0, 0, None, "script_error", "Another engine parsed this script.")
        if not tree.ok:
            first = next(p for p in tree.problems if p.severity == "error")
            return Result("", (), False, 0, 0, None, "script_error", first.message)
        return Run(tree, facts, self.limits, trace, rng).go()

    def reference(self) -> list[dict]:
        """Every block once, in registration order, for a generated reference page."""
        seen: dict[int, dict] = {}
        for spec in self.specs.values():
            seen.setdefault(
                id(spec),
                {
                    "names": list(spec.names),
                    "category": spec.category,
                    "doc": spec.doc,
                    "example": spec.example,
                    "gate": spec.gate,
                },
            )
        return list(seen.values())

    def _unknown(self, variables: set):
        """Words the problem for a name that isn't a block, once per name. Only the first few get a "did you mean"."""
        memo: dict[tuple, str] = {}
        spent = 0

        def message(n: Block) -> str:
            nonlocal spent
            key = n.name.strip().lower()
            spaced = self.loose and n.name != n.name.strip() and (key in self.specs or key in variables)
            mk = (key, spaced)
            if mk not in memo:
                shown = n.name.strip()[:32]
                if spaced:  # loose mode matches names with their spaces, like legacy
                    memo[mk] = f"Write {{{shown}}} with no spaces around the name. It prints as written."
                elif key in self.hints:
                    memo[mk] = f"{{{key}}} isn't in the Engine. {self.hints[key]}" + (" It prints as written." if self.loose else "")
                elif key in variables and n.param is not None:
                    memo[mk] = f"Lists in variables aren't in the Engine. Write {{{key}}} for the whole value."
                else:
                    pool = []
                    if len(memo) < HINTED:
                        for c in sorted([*self.specs, *variables], key=lambda c: (abs(len(c) - len(key)), c)):
                            spent += len(c) * len(key)
                            if spent > HINT_WORK:
                                break
                            pool.append(c)
                    close = difflib.get_close_matches(key, pool, n=1, cutoff=0.6)
                    hint = f" Did you mean {{{close[0]}}}?" if close else ""
                    memo[mk] = f"Unknown block {{{shown}}}.{hint} Type \\{{ for a brace."
            return memo[mk]

        return message

    def _binder(self, src: str):
        specs, hints, loose = self.specs, self.hints, self.loose

        def bind(name, name_ok, param, payload, start, end, problems, kids=(), bad=False):
            node = Block(name, param, payload, start, end, kids=kids)
            err = _Errors(src, node, problems, loose)
            # In loose mode a block that can't be read prints as written, and its blocks run in place.
            written = Block(name, param, payload, start, end, WRITTEN, None, kids) if loose else None
            if bad and loose:
                return written  # the parser has warned
            if not name_ok:
                err.shape("Block names must be written out. A block can't make another block's name.")
                return written or node
            key = name.strip().lower()
            spec = self.lookup(name)
            if spec is None:
                head, dot, tail = key.partition(".")
                var = name if loose else key
                if not key:
                    err.shape("Empty block {}. Type \\{ for a brace.")
                elif valid_var(var) and param is None and payload is None:
                    spec = VAR  # or a hint, once Engine.parse knows which names are assigned
                elif key in hints:
                    err.shape(f"{{{key}}} isn't in the Engine. {hints[key]}")
                elif dot and head in specs:
                    err.shape(f"Write {{{head}({tail[:32]})}} instead of {{{name.strip()[:40]}}}.")
                else:
                    return replace(written or node, data=UNKNOWN)
                if spec is None:
                    return written or node
            data = spec.compile(node, err, self)
            if err.shaped and loose:
                return written
            return Block(name, param, payload, start, end, spec, data, kids)

        return bind


HINTED = 5
HINT_WORK = 30_000  # character pairs "did you mean" may compare per parse, about 3 ms at worst
UNKNOWN = object()  # Block.data for a name that isn't a block. Engine.parse words the problem.


class _Errors:
    """The ``err`` that a spec's ``compile`` gets. ``err(message, at=block)`` adds a problem."""

    def __init__(self, src: str, node: Block, problems: list, loose: bool = False):
        self.src, self.node, self.problems, self.loose = src, node, problems, loose
        self.shaped = False

    def __call__(self, msg: str, at: Block | None = None):
        at = at or self.node
        self.problems.append(problem(self.src, msg, at.start, at.end))

    def shape(self, msg: str):
        """A block written in a form it doesn't take. In loose mode it prints as written."""
        self.shaped = True
        if self.loose:
            msg += " It prints as written."
        self.problems.append(problem(self.src, msg, self.node.start, self.node.end, "warning" if self.loose else "error"))

    def written(self, block: Block) -> str:
        """The block as the script writes it, cut short if long."""
        text = self.src[block.start : block.end]
        return text if len(text) <= 40 else text[:38] + "…}"
