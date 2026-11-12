"""The opt-in legacy options. Each case runs under the legacy Interpreter and the Engine with
the options on, and both must give the pinned text and commands.
"""

import random

import pytest

from .engine_vocab import facts, make_engine
from .test_engine_corpus import LEGACY
from TagScriptEngine import ProcessError, adapter
from TagScriptEngine.engine import BUILTINS, COMMAND, ActionBlock, Engine, Fact, Kind, Spec
from TagScriptEngine.engine.blocks import Assign, literal

FULL = dict(loose=True, legacy_stop=True, legacy_break=True, shadow_facts=True)
VOCAB = (Fact(("user",)), Fact(("args",)), ActionBlock(("c", "command"), "command", arg=COMMAND, field="text"))
SEED = {"user": "sam", "args": "a b c"}

# (script, options, text, commands)
CASES = [
    ("{foo:{user}}", "loose", "{foo:sam}", []),
    ("{foo:{c:ban x}}", "loose", "{foo:}", ["ban x"]),
    ("{foo(a|b):{if(1==1):x|y}}", "loose", "{foo(a|b):x}", []),
    ("{foo:{=(z):1}}{z}", "loose", "{foo:}1", []),
    ("{x}{=(x):1}{x}", "loose", "{x}1", []),
    ("{missing}", "loose", "{missing}", []),
    ("{ user}", "loose", "{ user}", []),
    ("{User}", "loose", "{User}", []),
    ("{=(User):hi}{User} {user}", "loose", "hi sam", []),
    ("{ if(1==1):a}", "loose", "{ if(1==1):a}", []),
    ("{IF(1==1):a}", "loose", "a", []),
    ("{c :ban x}", "loose", "{c :ban x}", []),
    ("{if.x}", "loose", "{if.x}", []),
    ("{cooldown(5):x}", "loose", "{cooldown(5):x}", []),
    ("{}", "loose", "{}", []),
    ("{{user}}", "loose", "{sam}", []),
    ("a } b", "loose", "a } b", []),
    ("a }{user}", "loose", "a }sam", []),
    ("}}{user}{{", "loose", "}}sam{{", []),
    ("{a {user} b", "loose", "{a sam b", []),
    ("{a{b{user}", "loose", "{a{bsam", []),
    ("{if(1==1):{a|b}", "loose", "{if(1==1):{a|b}", []),
    ("{if(1==1) :a|b}", "loose", "{if(1==1) :a|b}", []),
    ("{if(1==1)}", "loose", "{if(1==1)}", []),
    ("{math}", "loose", "{math}", []),
    ("{random}", "loose", "{random}", []),
    ("{replace(a):b}", "loose", "{replace(a):b}", []),
    ("{math:1+} {math:hello}", "loose", "{math:1+} {math:hello}", []),
    ("{substr(x):abc} {substr(-1):x}", "loose", "{substr(x):abc} {substr(-1):x}", []),
    ("{in():abc} {in(a):} {contains():abc} {index(a):}", "loose", "true false false -1", []),
    ("hi {user} {stop(1==1):bye} after", "legacy_stop", "hi sam bye", []),
    ("{c:one}text{stop(1==1):bye}{c:two}", "legacy_stop", "textbye", ["one"]),
    ("{if(1==1):a{user}{stop(1==1):x}b|c}", "legacy_stop", "{if(1==1):asamx", []),
    ("{if({stop(1==1):x}==y):a|b}", "legacy_stop", "{if(x", []),
    ("{stop(1==1):{stop(1==1):y}}", "legacy_stop", "{stop(1==1):y", []),
    ("pre {=(v):{stop(1==1):s}} post", "legacy_stop", "pre {=(v):s", []),
    ("{stop(1==2):no} yes", "legacy_stop", "yes", []),
    ("{stop:x} {stop} {stop()}", "loose legacy_stop", "{stop:x} {stop} {stop()}", []),
    ("{break(1==1):first}{c:after}{break(1==1):second} tail", "legacy_break", "second", ["after"]),
    ("{break(1==1)} gone", "legacy_break", "", []),
    ("{break(1==2):no} yes", "legacy_break", "yes", []),
    ("{break()} x", "legacy_break", "x", []),
    ("{stop(1==1):{break(1==1):b}s}", "legacy_break", "b", []),
    ("{break(1==1):brk}{c:x}{stop(1==1):stp}", "legacy_break legacy_stop", "brk", ["x"]),
    ("{=(args):new}{args}", "shadow_facts", "new", []),
    ("{args} {=(args):new} {args}", "shadow_facts", "a b c  new", []),
]


def engine(opts: str) -> Engine:
    return Engine(VOCAB, **{o: True for o in opts.split()})


@pytest.mark.parametrize("src, opts, text, commands", CASES, ids=[c[0] for c in CASES])
def test_engine_matches_legacy(src, opts, text, commands):
    res = LEGACY.process(src, {k: adapter.StringAdapter(v) for k, v in SEED.items()})
    assert (res.body, res.actions.get("commands", [])) == (text, commands)
    for e in (engine(opts), Engine(VOCAB, **FULL)):
        tree = e.parse(src)
        assert tree.ok, tree.problems
        got = e.run(tree, dict(SEED))
        assert got.error is None, got.detail
        assert (got.body, [p["text"] for p in got.plan]) == (text, commands)
        assert got.stopped == ("stop(1==1)" in src)


# Kept on purpose: the Engine stays lazy, strict blocks still fail, and it never crashes.
# (script, legacy, Engine, args): args stands in for member text, "a b c" when None.
DIFFERENT = [
    ("{if(1==1):{c:x}|{c:y}}", ("", ["x", "y"]), ("", ["x"]), None),
    ("{stop(1==2):{stop(1==1):y}}", ("{stop(1==2):y", []), ("", []), None),
    ("{if(1==1):{=(r):a}|{=(r):b}}{r}", ("b", []), ("a", []), None),
    ("{break(1==2):{=(x):v}}{x}", ("v", []), ("{x}", []), None),
    ("{if({args}):yes|no}", ("{if():yes|no}", []), ("no", []), ""),
    ("{if({args}):yes|no}", ("{if(a b c):yes|no}", []), ("no", []), None),
    ("{=(n):user}{{n}}", ("sam", []), ("{user}", []), None),
    ("{stop({args}==):need}{args}", ("need", []), ("x==x", []), "x==x"),
    ("{if({args}==):none|some}", ("none", []), ("some", []), "x==x"),
    ("{=(x):a|b}{if(1==1):{x}|no}", ("a|b|no", []), ("a|b", []), None),
    ("{=( x ):1}{x}", ("{x}", []), ("1", []), None),
    ("{=(x ):1}{x }", ("1", []), ("{x }", []), None),
    ("{substr(1):}", ("", []), ("{substr(1):}", []), None),
    ("{substr(1-2-3):hello there}", ("e", []), ("{substr(1-2-3):hello there}", []), None),
    ("{user(id)x}", ("sam", []), ("{user(id)x}", []), None),
    ("{math:2*3}", ("6.0", []), ("6", []), None),
    ("{=(x)}{x}", ("None", []), ("", []), None),
    ("{break} x", ProcessError, ("{break} x", []), None),
]


@pytest.mark.parametrize("src, legacy, eng, args", DIFFERENT, ids=[f"{c[0]} {c[3]}" for c in DIFFERENT])
def test_known_differences(src, legacy, eng, args):
    seed = {**SEED, "args": SEED["args"] if args is None else args}
    adapted = {k: adapter.StringAdapter(v) for k, v in seed.items()}
    if legacy is ProcessError:
        with pytest.raises(ProcessError):
            LEGACY.process(src, adapted)
    else:
        res = LEGACY.process(src, adapted)
        assert (res.body, res.actions.get("commands", [])) == legacy
    got = Engine(VOCAB, **FULL).run(src, seed)
    assert (got.body, [p["text"] for p in got.plan]) == eng


def test_random_picks_a_part():
    random.seed(1)
    assert LEGACY.process("{random:a~b}", {}).body in ("a", "b")
    assert Engine(VOCAB, **FULL).run("{random:a~b}", {}, rng=random.Random(1)).body in ("a", "b")


@pytest.mark.parametrize("src", ["{if(1==1):a|b|c}", "{=(a b):1}", "{c:{user}}", "{=(if):1}"])
def test_loose_keeps_real_errors(src):
    assert not Engine(VOCAB, **FULL).parse(src).ok


@pytest.mark.parametrize("src", ["pre {math:{args}+1} post {c:ping}", "pre {substr({args}):abc} post {c:ping}"])
def test_loose_member_input_still_fails_at_run_time(src):
    got = Engine(VOCAB, **FULL).run(src, {"args": "abc"})
    assert (got.error, got.plan) == ("script_error", ())


def test_loose_spaced_name_says_so():
    tree = Engine(VOCAB, loose=True).parse("{ upper } {=(x):1}{ x }")
    assert [p.message for p in tree.problems] == [
        f"Write {{{n}}} with no spaces around the name. It prints as written." for n in ("upper", "x")
    ]
    # Strict mode keeps the space before a (param), but must word it as 2.7.1 did.
    tree = Engine().parse("{=(user):<＠9>}{c:avatar { user(id)} }")
    assert [p.message for p in tree.problems] == [
        "Unknown block {c}. Type \\{ for a brace.",
        "Lists in variables aren't in the Engine. Write {user} for the whole value.",
    ]


def test_problem_cap_is_an_error():
    e = Engine(loose=True)
    assert e.parse("}" * 50).ok
    assert not e.parse("}" * 51).ok


def test_repr_stays_small():
    tree = Engine().parse("{upper:" * 32 + "x" + "}" * 32)
    assert len(repr(tree.root)) < 5_000 and len(repr(tree)) < 100_000


def test_loose_problems_are_warnings():
    tree = Engine(VOCAB, loose=True).parse("{foo} } {a {if(1==1)} {missing}")
    assert tree.ok and len(tree.problems) == 5
    assert {p.severity for p in tree.problems} == {"warning"}


def test_strict_is_unchanged():
    e = Engine(VOCAB)
    for src in ("{foo}", "a }", "{a", "{=(args):x}{args}", "{break(1==1):x}", "{if(1==1) :a}"):
        assert not e.parse(src).ok, src
    assert e.run("{stop(1==1)}", {}).body == ""
    assert e.run("{c:one}{stop(1==1):s}", {}).plan == ()


def test_shadowed_fact_cant_go_in_a_command():
    e = make_engine(shadow_facts=True)
    tree = e.parse("{=(user):<@1>}{c:avatar {user(id)} }")
    assert any("set as a variable" in p.message for p in tree.problems if p.severity == "error")
    assert e.parse("{c:avatar {user(id)} }").ok
    assert e.run("{=(user):x}{user(id)}", facts()).body == "x"


def test_only_facts_can_be_shadowed():
    e = make_engine(shadow_facts=True)
    for src in ("{=(c):x}", "{=(if):x}", "{=(addrole):x}", "{=(stop):x}"):
        assert not e.parse(src).ok, src


def test_fact_shadow_hook():
    class Words(Fact):
        def shadow(self, value, param):
            return value.split()[int(param) - 1]

    e = Engine((Words(("args",), params=("1", "2")),), shadow_facts=True)
    assert e.run("{=(args):a b}{args(2)}", {}).body == "b"

    class Args(Fact):
        def shadow(self, value, param):
            return value if param is None else value.split()[int(param) - 1]

    e = Engine((Args(("args",), params=("1", "2", None)),), shadow_facts=True)
    assert e.run("{args} {args(2)}", {"args": "x y"}).body == "x y x y"
    assert e.run("{=(args):a b}{args}/{args(2)}", {}).body == "a b/b"
    assert not e.parse("{args(3)}").ok


# Where a shadowed id must be refused: a branch, a wrapper loose mode prints, after the command,
# any case or spacing strict mode reads as the fact, every setter name, and other id facts.
SHADOWED = [
    ("{=(user):{match}}{if(1==1):{c:avatar {user(id)} }|}", "shadow_facts"),
    ("{=(user):<@9>}{foo:{c:avatar {user(id)} }}", "shadow_facts loose"),
    ("{c:avatar {user(id)} }{=(user):<@9>}", "shadow_facts"),
    ("{=(user):{match}}{c:avatar {User(id)} }", "shadow_facts"),
    ("{=(user):<@9>}{c:avatar { user(id)} }", "shadow_facts"),
    ("{let(user):<@9>}{c:avatar {user(id)} }", "shadow_facts loose"),
    ("{assign(user):<@9>}{c:avatar {user(id)} }", "shadow_facts loose"),
    ("{=(channel):<#5>}{c:info {channel(id)} }", "shadow_facts loose legacy_stop legacy_break"),
]


@pytest.mark.parametrize("src, opts", SHADOWED, ids=[c[0] for c in SHADOWED])
def test_shadowed_fact_is_refused_everywhere(src, opts):
    tree = make_engine(**{o: True for o in opts.split()}).parse(src)
    assert any("set as a variable" in p.message for p in tree.problems if p.severity == "error"), tree.problems


def test_setter_that_isnt_assign_cant_shadow_a_command():
    """The parse check knows only Assign. The run-time check catches any other setter."""

    class Setter(Spec):
        names = ("=", "let", "assign", "var")

        def compile(self, node, err, engine):
            return engine.var_key(literal(node.param))

        def value(self, node, r):
            r.vars[node.data] = r.text(node.payload)
            return ""

    e = make_engine(shadow_facts=True, builtins=tuple(b for b in BUILTINS if not isinstance(b, Assign)) + (Setter(),))
    tree = e.parse("{=(user):{match}}{c:avatar {user(id)} }")
    assert tree.ok
    got = e.run(tree, facts(match="<@999>"))
    assert got.plan == () and "set as a variable" in got.detail


def test_actions_kept_by_legacy_options_are_listed():
    e = make_engine(legacy_break=True)
    tree = e.parse("{break(1==1):x}{addrole:<@&5>}")
    assert [a.item for a in e.check(tree).actions] == [p for p in e.run(tree, facts()).plan] == [
        {"kind": "role", "op": "add", "id": "5"}
    ]
    e = make_engine(legacy_stop=True)
    tree = e.parse("{c:a}{stop(1==1):x}")
    assert [a.item["text"] for a in e.check(tree).actions] == [p["text"] for p in e.run(tree, facts()).plan] == ["a"]


def test_builtins_can_be_swapped():
    class LooseIf(Spec):
        names = ("if",)

        def value(self, node, r):
            return "mine"

    e = Engine(blocks=(LooseIf(),), builtins=tuple(b for b in BUILTINS if "if" not in b.names))
    assert e.run("{if(1==1):a}", {}).body == "mine"
    assert not Engine(builtins=()).parse("{if(1==1):a}").ok
    with pytest.raises(ValueError):
        Engine(blocks=(LooseIf(),))


def test_action_with_no_value_is_an_error():
    """The checker can't list an item its Kind parsed to None, so it must not run either."""
    e = Engine((ActionBlock(("act",), "act", arg=Kind("thing", lambda s: None), field="v"),))
    assert not e.parse("{act:x}").ok
