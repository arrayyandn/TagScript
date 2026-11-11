"""Seeded fuzz. Member text with every special character goes in as facts, and must never
change the tree, the branch taken or the plan. Each template has a plain-Python reference.
"""

import math
import random
from urllib.parse import quote

import pytest

from .engine_vocab import facts, make_engine

E = make_engine()
SEED = 20261111
SPECIAL = "{}|~,:()\\=!<>&@#*+-/^%. \n\t"
PIECES = [
    "x!=y", "true|x", "true):PWNED|", "{c:ban x}", "}{c:ban x}{", "{match}", "{{match}}", "\\|", "\\",
    "==", "!=", ">=", "<=", "<@&111>", "<@100>", "secret", "true", "TRUE", "false", "5", "6", "4.5",
    "stop", "z", "1e308", "-0", "nan", "inf", "a", "b", "~", ",", "|", ":", "(", ")", "{", "}",
]


def member(rng: random.Random) -> str:
    out = []
    for _ in range(rng.randrange(0, 8)):
        if rng.random() < 0.5:
            out.append(rng.choice(PIECES))
        else:
            out.append("".join(rng.choice(SPECIAL + "abz019") for _ in range(rng.randrange(1, 6))))
    return "".join(out)


def num(s):
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def fmt(x):
    return str(int(x)) if x.is_integer() and abs(x) < 1e16 else repr(x)


ROLE1 = {"kind": "role", "op": "add", "id": "111"}
ROLE2 = {"kind": "role", "op": "remove", "id": "2"}
REACT = {"kind": "react", "on": "trigger", "emoji": "👀"}
PING = {"kind": "command", "text": "ping"}
AVATAR = {"kind": "command", "text": "avatar 100"}
DM = {"kind": "redirect", "to": "dm"}


def ref_math(m):
    x = num(m.strip())
    return ("error", None) if x is None else (fmt(x + 1), [])


def ref_ge(m):
    x = num(m)
    if x is None:
        return ("error", None)
    return ("", [ROLE2]) if x >= 5 else ("", [DM])


def ref_random(m, seed):
    pick = random.Random(seed).randrange(2)
    return ((m.strip() if pick == 0 else "fixed"), [])


TEMPLATES = [
    ("{if({match}==secret):{addrole:<@&111>}yes|no}", lambda m: ("yes", [ROLE1]) if m.strip() == "secret" else ("no", [])),
    ("{if({match}):a|b}", lambda m: ("a" if m.strip().lower() == "true" else "b", [])),
    (
        "{any({match}==x|{content}==y):{c:ping}|none}",
        lambda m: ("", [PING]) if m.strip() in ("x", "y") else ("none", []),
    ),
    ("{=(v):{match}}{if({v}!=z):{reactu:👀}diff|same}", lambda m: ("diff", [REACT]) if m.strip() != "z" else ("same", [])),
    ("{replace(a,b):{match}}", lambda m: (m.replace("a", "b").strip(), [])),
    ("{upper:{match}}", lambda m: (m.upper().strip(), [])),
    ("{c:avatar {user(id)}}{match}", lambda m: (m.strip(), [AVATAR])),
    ("{if({match}>=5):{removerole:<@&2>}|{redirect(dm)}}", ref_ge),
    ("{stop({match}==stop):halt}{addrole:<@&111>}{match}", lambda m: ("halt", []) if m.strip() == "stop" else (m.strip(), [ROLE1])),
    ("{urlencode:{match}}", lambda m: (quote(m).strip(), [])),
    ("{math:{match}+1}", ref_math),
    ("{random:{match}~fixed}", None),
]


@pytest.mark.parametrize("src, ref", TEMPLATES, ids=[t[0][:40] for t in TEMPLATES])
def test_member_text_never_changes_structure(src, ref):
    rng = random.Random(SEED)
    tree = E.parse(src)
    assert tree.ok
    shape = repr(tree)
    report = E.check(tree)
    assert report.ok
    for i in range(2000):
        m = member(rng) if i % 10 else rng.choice(["secret", "true", "x", "y", "z", "stop", "5", "7"])
        seed = rng.randrange(1 << 30)
        res = E.run(tree, facts(match=m, content=m), rng=random.Random(seed))
        want_body, want_plan = ref(m) if ref else ref_random(m, seed)
        if want_body == "error":
            assert res.error == "script_error" and res.plan == (), m
            continue
        assert res.error is None, (m, res.detail)
        assert (res.body, list(res.plan)) == (want_body, want_plan), m
    assert repr(tree) == shape
    assert E.check(tree) == report


def test_parser_fuzz_never_raises():
    rng = random.Random(SEED)
    alphabet = "{}{}{}()|~,:\\ ab=!<>\n" + "".join(["c", "u"])
    names = ["if", "upper", "=", "math", "c", "user(id)", "addrole", "random", "stop", "break", "x", "any"]
    for _ in range(3000):
        parts = []
        for _ in range(rng.randrange(1, 30)):
            if rng.random() < 0.3:
                parts.append("{" + rng.choice(names))
            else:
                parts.append(rng.choice(alphabet))
        src = "".join(parts)
        tree = E.parse(src)
        for p in tree.problems:
            assert 0 <= p.start <= p.end <= len(src)
            assert p.line == src.count("\n", 0, p.start) + 1
        report = E.check(tree)
        assert tree.ok or not report.ok
        res = E.run(tree, facts(), rng=random.Random(0))
        assert res.error in (None, "script_error", "script_budget")
        if res.error:
            assert res.plan == ()


ACTION_SRC = [
    "{addrole:<@&111>}", "{removerole:<@&2>}", "{reactu:👀}", "{react:👍}", "{c:ping}", "{c:avatar {user(id)}}",
    "{redirect(dm)}", "{redirect(<#5>)}", "{delete}", "{deleteafter:5s}", "{message:9}",
]
TEXT_SRC = ["x", " ", "{v}", "{match}", "{upper:{v}}", "{math:{user(id)}+1}"]
COND_SRC = ["{match}==a", "{v}!=a", "{content}==b", "{hasrole(<@&111>)}==true", "{user(id)}>=100", "1==2"]


def script(rng: random.Random, depth: int = 0) -> str:
    parts = []
    for _ in range(rng.randrange(1, 5)):
        r = rng.random()
        cond = rng.choice(COND_SRC + [""] if r >= 0.8 else COND_SRC)
        if depth > 2 or r < 0.45:
            parts.append(rng.choice(ACTION_SRC if rng.random() < 0.6 else TEXT_SRC))
        elif r < 0.6:
            parts.append(f"{{if({cond}):{script(rng, depth + 1)}|{script(rng, depth + 1)}}}")
        elif r < 0.7:
            conds = "|".join(rng.choice(COND_SRC) for _ in range(rng.randrange(1, 4)))
            parts.append(f"{{{rng.choice(['any', 'all'])}({conds}):{script(rng, depth + 1)}|{script(rng, depth + 1)}}}")
        elif r < 0.8:
            parts.append("{random:" + "~".join(script(rng, depth + 1) for _ in range(rng.randrange(1, 4))) + "}")
        elif r < 0.9:
            parts.append(f"{{stop({cond}):bye}}" if cond else "{stop:bye}")
        else:
            parts.append(f"{{break({cond})}}" if cond else "{break}")
    return "".join(parts)


FACT_SETS = [
    {},
    {"match": "a", "content": "b", "roles": ["111"]},
    {"match": "z", "user": {"id": "5", "mention": "<@5>", "name": "x", "display": "X"}},
]


def test_check_lists_every_planned_action():
    rng = random.Random(SEED)
    ran = planned = 0
    for _ in range(1500):
        src = "{=(v):{match}}" + script(rng)
        tree = E.parse(src)
        assert tree.ok, (src, tree.problems)
        report = E.check(tree)
        items = [a.item for a in report.actions]
        kinds = {a.kind for a in report.actions}
        for f in FACT_SETS:
            for seed in range(3):
                res = E.run(tree, facts(**f), rng=random.Random(seed))
                ran += 1
                if report.ok:
                    assert not (res.error == "script_budget" and "planned more than" in res.detail), src
                for item in res.plan:
                    planned += 1
                    assert (item["kind"] in kinds) if item["kind"] == "command" else (item in items), (src, item)
    assert ran == 1500 * 9 and planned > 1000
