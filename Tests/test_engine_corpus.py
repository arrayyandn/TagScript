"""The conformance corpus: each case runs under the legacy Interpreter and the Engine.

It pins the legacy behaviours the Engine changes on purpose, and the injections it stops.
"""

import json
import pathlib
import random

import pytest

from .engine_vocab import facts, make_engine
from TagScriptEngine import Interpreter, ProcessError, adapter, block

CASES = json.loads((pathlib.Path(__file__).parent / "engine_corpus.json").read_text("utf-8"))
ENGINE = make_engine()
LEGACY = Interpreter(
    [
        block.AssignmentBlock(),
        block.StrictVariableGetterBlock(),
        block.IfBlock(),
        block.AnyBlock(),
        block.AllBlock(),
        block.RandomBlock(),
        block.MathBlock(),
        block.ReplaceBlock(),
        block.StopBlock(),
        block.BreakBlock(),
        block.URLEncodeBlock(),
        block.CommandBlock(),
    ]
)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_legacy(case):
    member = case.get("match", "hello")
    seed = {"match": adapter.StringAdapter(member), "content": adapter.StringAdapter(member)}
    want = case["legacy"]
    if "raises" in want:
        with pytest.raises(ProcessError):
            LEGACY.process(case["src"], seed)
        return
    res = LEGACY.process(case["src"], seed)
    if "body_in" in want:
        assert res.body in want["body_in"]
    else:
        assert res.body == want["body"]
    assert res.actions.get("commands", []) == want.get("commands", [])


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_engine(case):
    member = case.get("match", "hello")
    tree = ENGINE.parse(case["src"])
    want = case["engine"]
    if "problem" in want:
        assert not tree.ok
        assert any(want["problem"] in p.message for p in tree.problems), tree.problems
        return
    assert tree.ok, tree.problems
    res = ENGINE.run(tree, facts(match=member, content=member), rng=random.Random(0))
    if "error" in want:
        assert res.error == want["error"] and res.plan == ()
        return
    assert res.error is None, res.detail
    assert res.body == want["body"]
    if "plan" in want:
        assert list(res.plan) == want["plan"]
    if "plan_len" in want:
        assert len(res.plan) == want["plan_len"]
    assert res.stopped == want.get("stopped", False)


def test_corpus_is_large_enough():
    assert len(CASES) >= 20
