"""Running a tree: lazy branches, budgets, the plan and the trace."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from .blocks import BreakRun, Budget, Fail, StopRun
from .parse import Block, Sep, Tree

__all__ = ("Limits", "Result", "TraceStep", "Run")


@dataclass(frozen=True, slots=True)
class Limits:
    """Per-script caps (design §5). Override any of them with ``Engine(limits=Limits(...))``."""

    chars: int = 4000
    blocks: int = 1000
    depth: int = 32
    steps: int = 5000
    chars_per_step: int = 64
    deadline_ms: float = 20.0
    clock_every: int = 64
    value: int = 4000
    work: int = 20000
    reply: int = 2000
    items: int = 12
    kinds: dict = field(default_factory=lambda: {"command": 1, "react": 5, "role": 5, "message": 1})
    trace: int = 200
    math_chars: int = 200
    math_depth: int = 16
    problems: int = 50


@dataclass(frozen=True, slots=True)
class TraceStep:
    block: str
    line: int
    col: int
    result: str

    def to_json(self) -> dict:
        return {"block": self.block, "line": self.line, "col": self.col, "result": self.result}


@dataclass(frozen=True, slots=True)
class Result:
    """``error`` is None, ``"script_error"`` or ``"script_budget"``. On an error there is no plan.

    ``cpu_us`` is this thread's CPU time for the run only, not parse or check. It is coarse on
    Windows (0 or 15,625), so time parse, check and run yourself when you need a real number.
    """

    body: str
    plan: tuple[dict, ...]
    stopped: bool
    steps: int
    cpu_us: int
    trace: tuple[TraceStep, ...] | None = None
    error: str | None = None
    detail: str | None = None

    def to_json(self) -> dict:
        if self.error:
            return {"v": 1, "error": self.error, "detail": self.detail, "cpu_us": self.cpu_us}
        return {
            "v": 1,
            "body": self.body,
            "plan": [dict(p) for p in self.plan],
            "stopped": self.stopped,
            "cpu_us": self.cpu_us,
        }


class Run:
    """One run of one tree. Not shared between threads."""

    def __init__(self, tree: Tree, facts: dict, limits: Limits, trace: bool, rng):
        self.tree, self.facts, self.limits = tree, facts, limits
        self.rng = rng if rng is not None else random.Random()
        self.steps = 0
        self.work = 0
        self.next_clock = limits.clock_every
        self.deadline = 0
        self.vars: dict[str, str] = {}
        self.plan: list[dict] = []
        self.trace: list[list] | None = [] if trace else None

    def spend(self, n: int):
        self.steps += n
        if self.steps > self.limits.steps:
            raise Budget(f"The script took more than {self.limits.steps:,} steps.")
        if self.steps >= self.next_clock:
            self.next_clock = self.steps + self.limits.clock_every
            if time.perf_counter_ns() > self.deadline:
                raise Budget(f"The script took longer than {self.limits.deadline_ms:g} ms.")

    def charge(self, n: int):
        """Output work: every character produced, at every level."""
        before = self.work
        self.work += n
        if self.work > self.limits.work:
            raise Budget(f"The script made more than {self.limits.work:,} characters.")
        per = self.limits.chars_per_step
        if self.work // per != before // per:
            self.spend(self.work // per - before // per)

    def emit(self, seq: tuple, out: list):
        for part in seq:
            if part.__class__ is str:
                self.charge(len(part))
                out.append(part)
            elif part.__class__ is Sep:
                self.charge(1)
                out.append(part.char)
            else:
                spec = part.spec
                self.spend(spec.cost)
                step = self._trace(part)
                if spec.branches:
                    arm, label = spec.choose(part, self)
                    if step:
                        step[1] = label
                    if arm:
                        self.emit(arm, out)
                else:
                    v = spec.value(part, self)
                    if len(v) > self.limits.value:
                        raise Budget(f"A value is over {self.limits.value:,} characters.")
                    if step:
                        step[1] = v if spec.category != "action" else f"planned {self.plan[-1]}"
                    self.charge(len(v))
                    out.append(v)

    def text(self, seq: tuple | None) -> str:
        if not seq:
            return ""
        out: list[str] = []
        self.emit(seq, out)
        s = "".join(out)
        if len(s) > self.limits.value:
            raise Budget(f"A value is over {self.limits.value:,} characters.")
        return s

    def _trace(self, node: Block):
        if self.trace is None or len(self.trace) >= self.limits.trace:
            return None
        step = [node, ""]
        self.trace.append(step)
        return step

    def add(self, item: dict, replace: bool):
        kind = item["kind"]
        if replace:
            self.plan = [p for p in self.plan if p["kind"] != kind]
        cap = self.limits.kinds.get(kind)
        if cap is not None and sum(p["kind"] == kind for p in self.plan) >= cap:
            raise Budget(f"The script planned more than {cap} {kind} action{'s' * (cap != 1)}.")
        if len(self.plan) >= self.limits.items:
            raise Budget(f"The script planned more than {self.limits.items} actions.")
        self.plan.append(item)

    def go(self) -> Result:
        cpu0 = time.thread_time_ns()
        self.deadline = time.perf_counter_ns() + int(self.limits.deadline_ms * 1e6)
        out: list[str] = []
        stopped = False
        error = detail = None
        try:
            try:
                self.emit(self.tree.root, out)
            except BreakRun:
                pass
            except StopRun as s:
                out, stopped = [s.text], True
                self.plan = []
            body = "".join(out).strip()[: self.limits.reply]  # cut like tags, the plan stays
        except Budget as e:
            error, detail = "script_budget", str(e)
        except Fail as e:
            error, detail = "script_error", str(e)
        except Exception as e:  # a bug in a block must not take the caller down
            error, detail = "script_error", f"{type(e).__name__}: {e}"[:200]
        cpu_us = (time.thread_time_ns() - cpu0) // 1000
        trace = None
        if self.trace is not None:
            trace = tuple(self._step(node, result) for node, result in self.trace)
        if error:
            return Result("", (), False, self.steps, cpu_us, trace, error, detail)
        return Result(body, tuple(self.plan), stopped, self.steps, cpu_us, trace)

    def _step(self, node: Block, result: str) -> TraceStep:
        src = self.tree.src
        line = src.count("\n", 0, node.start) + 1
        col = node.start - (src.rfind("\n", 0, node.start) + 1) + 1
        shown = src[node.start : node.end]
        if len(shown) > 80:
            shown = shown[:77] + "..."
        return TraceStep(shown, line, col, result if len(result) <= 100 else result[:97] + "...")
