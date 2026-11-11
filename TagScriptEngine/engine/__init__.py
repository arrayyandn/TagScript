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

from .blocks import BUILTINS, DEFAULT_HINTS, VAR, Assign, Fact, Spec, valid_var
from .check import Action, Report, check
from .parse import Block, Problem, Tree, capped, parse, problem
from .plan import COMMAND, DURATION, EMOJI, ROLE, SNOWFLAKE, TARGET, ActionBlock, Kind
from .run import Limits, Result, Run, TraceStep

__all__ = (
    "Engine",
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
    ``hints`` maps a name that isn't in the Engine to what to use instead.
    """

    def __init__(self, blocks=(), *, limits: Limits | None = None, hints: dict | None = None):
        self.limits = limits or Limits()
        self.hints = {**DEFAULT_HINTS, **(hints or {})}
        self.specs: dict[str, Spec] = {}
        self.register(*BUILTINS, *blocks)

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
        )
        assigned = {n.data for n in tree.blocks if isinstance(n.spec, Assign) and n.data}
        unknown = self._unknown(assigned)
        problems = list(tree.problems)
        for n in tree.blocks:
            if len(problems) > lim.problems:
                break
            if (n.spec is VAR and n.data not in assigned) or (n.spec is None and n.data is UNKNOWN):
                problems.append(problem(src, unknown(n), n.start, n.end))
        return replace(tree, problems=capped(problems, lim.problems), engine=self)

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
        memo: dict[str, str] = {}
        spent = 0

        def message(n: Block) -> str:
            nonlocal spent
            key = n.name.strip().lower()
            if key not in memo:
                shown = n.name.strip()[:32]
                if key in self.hints:
                    memo[key] = f"{{{key}}} isn't in the Engine. {self.hints[key]}"
                elif key in variables and n.param is not None:
                    memo[key] = f"Lists in variables aren't in the Engine. Write {{{key}}} for the whole value."
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
                    memo[key] = f"Unknown block {{{shown}}}.{hint} Type \\{{ for a brace."
            return memo[key]

        return message

    def _binder(self, src: str):
        specs, hints = self.specs, self.hints

        def bind(name, name_ok, param, payload, start, end, problems):
            node = Block(name, param, payload, start, end)
            err = _Errors(src, node, problems)
            if not name_ok:
                err("Block names must be written out. A block can't make another block's name.")
                return node
            key = name.strip().lower()
            spec = specs.get(key)
            if spec is None:
                head, dot, tail = key.partition(".")
                if not key:
                    err("Empty block {}. Type \\{ for a brace.")
                elif valid_var(key) and param is None and payload is None:
                    spec = VAR  # or a hint, once Engine.parse knows which names are assigned
                elif key in hints:
                    err(f"{{{key}}} isn't in the Engine. {hints[key]}")
                elif dot and head in specs:
                    err(f"Write {{{head}({tail[:32]})}} instead of {{{name.strip()[:40]}}}.")
                else:
                    return Block(name, param, payload, start, end, None, UNKNOWN)
                if spec is None:
                    return node
            return Block(name, param, payload, start, end, spec, spec.compile(node, err, self))

        return bind


HINTED = 5
HINT_WORK = 30_000  # character pairs "did you mean" may compare per parse, about 3 ms at worst
UNKNOWN = object()  # Block.data for a name that isn't a block. Engine.parse words the problem.


class _Errors:
    """The ``err`` that a spec's ``compile`` gets. ``err(message, at=block)`` adds a problem."""

    def __init__(self, src: str, node: Block, problems: list):
        self.src, self.node, self.problems = src, node, problems

    def __call__(self, msg: str, at: Block | None = None):
        at = at or self.node
        self.problems.append(problem(self.src, msg, at.start, at.end))

    def written(self, block: Block) -> str:
        """The block as the script writes it, cut short if long."""
        text = self.src[block.start : block.end]
        return text if len(text) <= 40 else text[:38] + "…}"
