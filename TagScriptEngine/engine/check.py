"""The save check: problems, every action in every branch, and the user ids written out.

It reads the same tree that runs, so a branch that isn't taken today is still checked.
"""

from __future__ import annotations

from dataclasses import dataclass

from .blocks import Spec
from .parse import Block, Problem, Tree, capped, problem
from .plan import ActionBlock

__all__ = ("Action", "Report", "check")


@dataclass(frozen=True, slots=True)
class Action:
    """One action block, wherever it sits. ``block`` is its main name, however it was written,
    and ``item`` is the plan item as written."""

    block: str
    kind: str
    item: dict
    gate: str | None
    line: int
    col: int
    start: int
    end: int

    def to_json(self) -> dict:
        return {
            "block": self.block,
            "kind": self.kind,
            "item": dict(self.item),
            "gate": self.gate,
            "line": self.line,
            "col": self.col,
        }


@dataclass(frozen=True, slots=True)
class Report:
    problems: tuple[Problem, ...]
    actions: tuple[Action, ...]
    user_ids: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not any(p.severity == "error" for p in self.problems)

    def to_json(self) -> dict:
        return {
            "ok": self.ok,
            "problems": [p.to_json() for p in self.problems],
            "actions": [a.to_json() for a in self.actions],
            "user_ids": list(self.user_ids),
        }


def check(tree: Tree, ctx, limits) -> Report:
    src = tree.src
    problems = list(tree.problems)
    actions: list[Action] = []
    for node in tree.blocks:
        spec = node.spec
        if spec is None:
            continue
        if isinstance(spec, ActionBlock) and (spec.arg is None or node.data is not None):
            p = problem(src, "", node.start, node.end)
            actions.append(
                Action(spec.names[0], spec.kind, spec.item(node, src), spec.gate, p.line, p.col, node.start, node.end)
            )
        for msg in spec.check(node, ctx):
            problems.append(problem(src, msg, node.start, node.end))
    if tree.ok:
        problems.extend(_caps(tree, actions, limits))
    return Report(capped(problems, limits.problems), tuple(actions), _user_ids(tree))


def _caps(tree: Tree, actions: list[Action], limits) -> list[Problem]:
    """The most actions of each kind that any one path can plan.

    shortcut: a replace kind (redirect, delete) counts once per block toward the 12-item total,
    so a script with many of them can be flagged early. Fine while scripts stay this small.
    """
    counts: dict[int, dict[str, int]] = {}

    def seq(parts) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in parts or ():
            if p.__class__ is Block:
                for k, v in counts.get(id(p), {}).items():
                    out[k] = out.get(k, 0) + v
        return out

    replaced: set[str] = set()
    for node in tree.blocks:  # children close before their parents
        spec: Spec = node.spec
        if spec is None:
            continue
        always, arms = spec.paths(node)
        c = seq(())
        for s in always:
            for k, v in seq(s).items():
                c[k] = c.get(k, 0) + v
        best: dict[str, int] = {}
        for a in arms:
            for k, v in seq(a).items():
                best[k] = max(best.get(k, 0), v)
        for k, v in best.items():
            c[k] = c.get(k, 0) + v
        if isinstance(spec, ActionBlock):
            c[spec.kind] = c.get(spec.kind, 0) + 1
            c["*"] = c.get("*", 0) + 1
            if spec.replace:
                replaced.add(spec.kind)
        counts[id(node)] = c
    total = seq(tree.root)
    out = []
    for kind, cap in limits.kinds.items():
        n = 1 if kind in replaced and total.get(kind) else total.get(kind, 0)
        if n > cap:
            first = next(a for a in actions if a.kind == kind)
            msg = f"This script can plan {n} {kind} actions. The most is {cap}."
            out.append(problem(tree.src, msg, first.start, first.end))
    if total.get("*", 0) > limits.items:
        first = actions[0]
        msg = f"This script can plan {total['*']} actions. The most is {limits.items}."
        out.append(problem(tree.src, msg, first.start, first.end))
    return out


def _user_ids(tree: Tree) -> tuple[str, ...]:
    """User mentions written anywhere in the script's own text, like <@123>: the reply,
    conditions and command text alike."""
    found: dict[str, None] = {}
    texts = [p for p in tree.root if p.__class__ is str]
    for node in tree.blocks:
        for s in (node.param, node.payload):
            texts.extend(p for p in s or () if p.__class__ is str)
    for text in texts:
        i = text.find("<@")
        while i != -1:
            j = i + 2 + (text[i + 2 : i + 3] == "!")
            k = j
            while k < len(text) and k - j < 20 and text[k].isascii() and text[k].isdigit():
                k += 1
            if k > j and text[k : k + 1] == ">":
                found.setdefault(text[j:k])
            i = text.find("<@", i + 2)
    return tuple(found)
