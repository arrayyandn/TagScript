import ast
import pathlib
import random
import subprocess
import sys
import time

import pytest

from TagScriptEngine import Engine, Interpreter, block
from TagScriptEngine.engine import ActionBlock, Fact, Limits, Spec
from TagScriptEngine.engine.parse import Block, Sep

from .engine_vocab import facts, make_engine

E = make_engine()


def run(src, **kw):
    tree = E.parse(src)
    assert tree.ok, [p.message for p in tree.problems]
    return E.run(tree, facts(**kw.pop("f", {})), rng=random.Random(0), **kw)


def body(src, **f):
    res = run(src, f=f)
    assert res.error is None, res.detail
    return res.body


def problems(src, engine=E):
    return [p.message for p in engine.parse(src).problems]


def problem(src, engine=E):
    found = problems(src, engine)
    assert found, f"no problem for {src!r}"
    return found[0]


# Parser


def test_tree_has_spans_and_positions():
    tree = E.parse("hi\n  {upper:{user(name)}}")
    upper, = [b for b in tree.blocks if b.name == "upper"]
    assert tree.src[upper.start : upper.end] == "{upper:{user(name)}}"
    p = E.parse("ok\nab {nope}").problems[0]
    assert (p.line, p.col, p.start, p.end) == (2, 4, 6, 12)


def test_tree_is_immutable():
    tree = E.parse("{upper:a}")
    with pytest.raises(AttributeError):
        tree.root = ()
    with pytest.raises(AttributeError):
        tree.blocks[0].payload = ("b",)


def test_separators_only_inside_blocks():
    assert body("a|b~c,d:(e)") == "a|b~c,d:(e)"
    tree = E.parse("{if(1==1):a|b}")
    assert any(isinstance(p, Sep) for p in tree.blocks[0].payload)


@pytest.mark.parametrize("ch", list("{}|:()~,\\"))
def test_escapes(ch):
    assert body(f"x\\{ch}y") == f"x{ch}y"
    assert body(f"{{if(1==1):x\\{ch}y|n}}") == f"x{ch}y"


def test_unknown_escape_keeps_backslash():
    assert body("a\\nb\\") == "a\\nb\\"


@pytest.mark.parametrize(
    "src, msg",
    [
        ("}", "Unmatched }"),
        ("{upper:a", "Missing } to close {upper"),
        ("{user(id}", "Missing ) in {user("),
        ("{user(id)x}", "Expected : or } after )"),
        ("{}", "Empty block {}"),
        ("{{match}}", "Block names must be written out"),
        ("{=({content}):x}", "Variable names must be written out"),
        ("{addrol:<@&1>}", "Unknown block {addrol}. Did you mean {addrole}? Type \\{ for a brace."),
        ("{a b}", "Unknown block {a b}."),
        ("{cooldown}", "{cooldown} isn't in the Engine. Cooldowns are a trigger setting."),
        ("{require(<@&1>)}", "Who can use a trigger is a trigger setting."),
        ("{user.id}", "Write {user(id)} instead of {user.id}."),
        ("{if(1==1)}", "{if} is written like"),
        ("{if():a}", "{if} is written like"),
        ("{upper(x):a}", "{upper} is written like"),
        ("{random(5):a~b}", "{random} is written like"),
        ("{replace(a):b}", "{replace} is written like {replace(old,new):text}"),
        ("{urlencode(x):a}", "{urlencode} only takes (+)"),
        ("{user(age)}", "{user} takes one of"),
        ("{user({match})}", "Write the part in () out"),
        ("{break:text}", "{break} keeps the reply so far and takes no text"),
        ("{=(if):x}", "{if} is a block"),
        ("{=(a b):x}", "can't be a variable name"),
        ("{x}", "Unknown block {x}."),
        ("{=(colour):red}{colour}{color}", "Did you mean {colour}?"),
        ("{m:1+1}", "{m} isn't in the Engine. Use {math} instead."),
        ("{calc:1}", "Use {math} instead."),
        ("{+:1}", "Use {math} instead."),
        ("{m}", "Use {math} instead."),
        ("{or(a==b):x}", "{or} isn't in the Engine. Use {any} instead."),
        ("{and(a==b):x}", "Use {all} instead."),
        ("{#:a,b}", "Use {random} instead."),
        ("{=(a):x,y}{a(1)}", "Lists in variables aren't in the Engine. Write {a} for the whole value."),
        ("{addrole:<@&5>}{stop:{break}}after", "{break} can't go inside {stop}"),
        ("{stop({break}):x}", "{break} can't go inside {stop}"),
        ("{stop:{if(1==1):{break}|x}}", "{break} can't go inside {stop}"),
        ("{whitelist(<@&1>)}", "{whitelist} isn't in the Engine. Who can use a trigger is a trigger setting."),
        ("{halt}", "{halt} isn't in the Engine. Use {stop} instead."),
        ("{error:x}", "{error} isn't in the Engine. Use {stop} instead."),
        ("{short}", "{short} isn't in the Engine. Use {break} instead."),
        ("{shortcircuit(1==1)}", "{shortcircuit} isn't in the Engine. Use {break} instead."),
        ("{?:hi}", "{?} isn't in the Engine. Use {random:text~} instead."),
        ("{substring(1-3):abc}", "{substring} isn't in the Engine. Use {substr} instead."),
        ("{strf:%Y}", "{strf} isn't in the Engine. There's no date or time formatting."),
        ("{unix}", "{unix} isn't in the Engine. There's no date or time formatting."),
        ("{python(a):b}", "Unknown block {python}."),
        ("{in():abc}", "{in} is written like {in(x):text}."),
        ("{contains(a)}", "{contains} is written like {contains(x):text}."),
        ("{index:a b}", "{index} is written like {index(x):text}."),
        ("{substr(2)}", "{substr} is written like {substr(2-5):text}."),
        ("{substr(-2):abc}", "{substr} takes (start) or (start-end), with numbers of 0 or more, not '-2'."),
        ("{substr(1-2-3):abc}", "not '1-2-3'."),
        ("{substr(x):abc}", "not 'x'."),
        ("{substr(inf):abc}", "not 'inf'."),
        ("{substr(1-):abc}", "not '1-'."),
        ("{=(index):5}", "{index} is a block"),
    ],
)
def test_save_errors(src, msg):
    assert any(msg in m for m in problems(src)), problems(src)


def test_hinted_names_still_work_as_variables():
    assert body("{=(m):5}{m} {=(or):y}{or}") == "5 y"
    assert body("{if(1==1):{break}}{stop:x}") == ""


def test_problems_are_capped():
    found = problems("}" * 4000)
    assert len(found) == 51 and found[-1] == "…and more problems. Fix these first."
    assert len(E.check(E.parse("}" * 4000)).problems) == 51
    assert len(problems("}" * 50)) == 50

    class Picky(Fact):
        def check(self, node, ctx):
            return ["Not here."]

    eng = Engine([Picky(("thing",))])
    rep = eng.check(eng.parse("}" * 50 + "{thing}"))
    assert len(rep.problems) == 51 and rep.problems[-1].message == "…and more problems. Fix these first."
    assert E.parse("}" * 51 + "{upper:a}").blocks == ()
    assert len(E.parse("}" * 50 + "{upper:a}").blocks) == 1


def test_only_the_first_unknown_names_get_a_hint():
    found = problems("".join(f"{{addrol{c}}}" for c in "abcdefgh") + "{reacte}" * 3)
    assert len(found) == 11 and sum("Did you mean" in m for m in found) == 5
    (same,) = set(problems("{reacte}" * 50))
    assert "Did you mean {react}?" in same


def hostile_names():
    rng = random.Random(1)
    src = "".join("{=(" + "".join(rng.choice("ab") for _ in range(7)) + "):x}" for _ in range(128))
    return src + "{bbbbbz}" * ((4000 - len(src)) // 8)


def distinct_names():
    src = hostile_names()[:2000]
    return src[: src.rindex("}") + 1] + "".join(f"{{bbbb{i:03d}}}" for i in range(200))


def long_names():
    src = "".join(f"{{=(v{i:031d}):x}}" for i in range(90))
    return src + "".join(f"{{w{k}{'0' * 30}}}" for k in range(6))


@pytest.mark.parametrize(
    "src",
    [
        hostile_names(),
        distinct_names(),
        long_names(),
        "{reacte(a)}" * 363,
        "}" * 4000,
        "{any(" + "|" * 3988 + "):a}",
    ],
    ids=["similar names", "distinct names", "long names", "unknown with param", "unmatched", "empty conditions"],
)
def test_hostile_scripts_parse_fast(src):
    assert len(src) <= 4000
    best = min(_timed(lambda: E.check(E.parse(src))) for _ in range(5))
    assert best < 0.03, f"{best * 1000:.1f} ms"


def _timed(fn):
    t = time.perf_counter()
    fn()
    return time.perf_counter() - t


def test_limits_on_size():
    small = make_engine(limits=Limits(chars=30, blocks=3, depth=2))
    assert "over 30 characters" in problem("x" * 31, small)
    assert "more than 3 blocks" in problem("{a}{a}{a}{a}", small)
    assert "nested more than 2 deep" in problem("{upper:{upper:{upper:a}}}", small)
    assert small.parse("{upper:{upper:a}}").ok
    assert "over 4,000 characters" in problem("x" * 4001)


def test_parser_is_iterative():
    deep = Engine(limits=Limits(chars=200_000, blocks=50_000, depth=50_000))
    tree = deep.parse("{upper:" * 20_000 + "a" + "}" * 20_000)
    assert tree.ok and tree.depth == 20_000
    assert body("{=(x):a}" + "{x}" * 990) == "a" * 990


# Lazy evaluation


def test_only_the_taken_branch_runs():
    res = run("{if(1==2):{c:ban x}|{c:kick y}}")
    assert res.plan == ({"kind": "command", "text": "kick y"},)
    res = run("{any(1==2|2==3):{addrole:1}|{removerole:2}}{all(1==1|2==2):{reactu:👀}|{react:👀}}")
    assert [p["kind"] + p.get("op", p.get("on", "")) for p in res.plan] == ["roleremove", "reacttrigger"]


def test_untaken_stop_and_break_never_fire():
    assert body("{if(1==2):{stop:no}|yes} {if(1==2):{break}} after") == "yes  after"


def test_random_runs_one_option():
    for seed in range(20):
        res = E.run(E.parse("{random:{addrole:1}~{addrole:2}~{addrole:3}}"), facts(), rng=random.Random(seed))
        assert len(res.plan) == 1
    picks = {E.run(E.parse("{random:a,b}"), facts(), rng=random.Random(s)).body for s in range(40)}
    assert picks == {"a", "b"}


def test_rng_is_per_run_and_seedable():
    tree = E.parse("{random:a~b~c~d~e~f~g~h}{random:a~b~c~d~e~f~g~h}")
    one = [E.run(tree, facts(), rng=random.Random(7)).body for _ in range(3)]
    assert len(set(one)) == 1
    assert len({E.run(tree, facts()).body for _ in range(30)}) > 1


def test_conditions():
    cases = {
        "{if(a==a):y|n}": "y",
        "{if( a == a ):y|n}": "y",
        "{if(a!=a):y|n}": "n",
        "{if(3>2):y|n}": "y",
        "{if(3<2):y|n}": "n",
        "{if(2>=2):y|n}": "y",
        "{if(2<=1):y|n}": "n",
        "{if(x==2):y|n}": "n",
        "{if(true):y|n}": "y",
        "{if(TRUE):y|n}": "y",
        "{if(yes):y|n}": "n",
        "{if(1==2):y}": "",
        "{if({hasrole(<@&111>)}):y|n}": "n",
    }
    for src, want in cases.items():
        assert body(src) == want, src
    assert body("{if({hasrole(<@&111>)}):y|n}", roles=["111"]) == "y"


AGE_GATE = "{stop({match}<18):Too young.}{addrole:<@&5>}Welcome"


@pytest.mark.parametrize("match", ["17 years", "seventeen", ""])
def test_ordered_compare_on_text_is_an_error(match):
    res = run(AGE_GATE, f={"match": match})
    assert (res.error, res.plan, res.body) == ("script_error", (), "")
    assert res.detail == f"Can't compare {match!r} with '18': both sides of < must be numbers."


def test_ordered_compare_on_numbers_still_works():
    res = run(AGE_GATE, f={"match": "17"})
    assert (res.error, res.body, res.plan, res.stopped) == (None, "Too young.", (), True)
    assert run(AGE_GATE, f={"match": "18"}).plan == ({"kind": "role", "op": "add", "id": "5"},)


@pytest.mark.parametrize(
    "src, want",
    [
        ("{if(1==2):{if(x<1):a|b}|ok}", "ok"),
        ("{any(1==1|x<1):y|n}", "y"),
        ("{all(1==2|x<1):y|n}", "n"),
        ("{if(1==2):{stop(x<1):bye}|ok}", "ok"),
        ("{if(x==1):y|n}{if(x!=1):y|n}{if(yes):y|n}", "nyn"),
    ],
)
def test_unreached_or_unordered_compare_is_fine(src, want):
    assert body(src) == want


@pytest.mark.parametrize(
    "src", ["{if(x<1):y|n}", "{any(1==2|x>1):y|n}", "{all(1==1|x>=1):y|n}", "{stop(x<=1):bye}", "{break(1>x)}"]
)
def test_reached_ordered_compare_on_text_is_an_error(src):
    assert run(src).error == "script_error"


def test_stop_drops_actions_and_replies():
    res = run("{addrole:1}hello {stop(1==1):  bye  }{addrole:2}")
    assert (res.body, res.plan, res.stopped) == ("bye", (), True)
    assert run("{stop}").body == ""
    assert run("{redirect(dm)}{stop:bye}").plan == ()


def test_break_keeps_reply_and_plan():
    res = run("{addrole:1}hello {if(1==1):there {break(1==1)} x} {addrole:2}")
    assert (res.body, res.plan, res.stopped) == ("hello there", ({"kind": "role", "op": "add", "id": "1"},), False)


def test_variables():
    assert body("{x}{=(X):1}{x}{let(y):2}{assign(z):{y}3}{Z}") == "123"
    assert body("{=(a):  padded  }[{a}]") == "[  padded  ]"


def test_value_is_never_parsed_again():
    assert body(r"{=(a):\{\}|x}{if(1==1):{a}}") == "{}|x"
    assert body("{upper:{match}}", match="{c:ban x}|y") == "{C:BAN X}|Y"


def test_text_blocks():
    assert body("{upper:abc}{lower:DEF}") == "ABCdef"
    assert body("{urlencode:a b/c}|{urlencode(+):a b/c}") == "a%20b/c|a+b%2Fc"
    assert body("{replace(a,o):banana}{replace(,-):ab}") == "bonono-a-b-"
    assert body("{replace(a\\,b,x):a,b}") == "x"


def test_reply_is_trimmed():
    assert body("  \n hi \n ") == "hi"


LEGACY_TEXT = Interpreter([block.PythonBlock(), block.SubstringBlock()])


@pytest.mark.parametrize(
    "src, want",
    [
        ("{in(apple pie):banana pie apple pie}", "true"),
        ("{in(a):cot}", "false"),
        ("{in( pie):apie}", "false"),
        ("{IN(a):cat}", "true"),
        ("{contains(feel):How does it feel}", "true"),
        ("{contains(fe):How does it feel}", "false"),
        ("{contains(muted?):to be muted?}", "true"),
        ("{index(eat):I love to eat food.}", "3"),
        ("{index(food):I love to eat food.}", "-1"),
        ("{index(a):a a a}", "0"),
        ("{index( love):I love}", "-1"),
        ("{substr(2):abcdef}", "cdef"),
        ("{substr(1-3):abcdef}", "bc"),
        ("{substr(1.9-3.2):abcdef}", "bc"),
        ("{substr( 2 - 4 ):abcdef}", "cd"),
        ("{substr(5-2):abcdef}", ""),
        ("{substr(99):abc}", ""),
        ("{substr(1e1):abcdefghijklmn}", "klmn"),
        ("{substr(0-1_0):abcdefghijklm}", "abcdefghij"),
        ("{substr(1e300):abc}", ""),
    ],
)
def test_search_and_substr_match_legacy(src, want):
    assert body(src) == want
    assert LEGACY_TEXT.process(src).body == want


@pytest.mark.parametrize(
    "src, match, want",
    [
        ("{in({match}):secret}", "s):s", "false"),
        ("{in({match}):abc}", "", "true"),
        ("{index({match}):a b c}", "c):c", "-1"),
        ("{contains({match}):a b c}", "a b", "false"),
        ("{substr({match}):abcdef}", "1-3", "bc"),
        ("{substr(0-5):{match}}", "{c:ban x}", "{c:ba"),
        ("{in(a):{match}}", "}{c:ban x}", "true"),
    ],
)
def test_search_and_substr_keep_member_text_as_text(src, match, want):
    res = run(src, f={"match": match})
    assert (res.body, res.plan, res.error) == (want, (), None)


@pytest.mark.parametrize("match", ["-2", "", "x", "1-2-3", "1):x}{c:ban x}{substr(1", "nan"])
def test_substr_needs_numbers_from_members_too(match):
    res = run("{addrole:<@&5>}{substr({match}):abcdef}", f={"match": match})
    assert (res.error, res.plan) == ("script_error", ())
    assert res.detail == f"{{substr}} takes (start) or (start-end), with numbers of 0 or more, not {match!r}."


def test_search_and_substr_are_charged():
    a = "{=(a):" + "x" * 3000 + "}"
    assert run(a + "{in(y):{a}}").steps >= 3000 // 64
    for blk in ("{in(y):{a}}", "{contains(y):{a}}", "{index(y):{a}}", "{substr(1):{a}}"):
        assert run(a + blk * 10).error == "script_budget", blk


def test_checker_sees_nothing_in_search_and_substr():
    report = E.check(E.parse("{in(a):b}{contains(a):b}{index({match}):b}{substr(1):{user(id)}}"))
    assert report.ok and report.actions == () and report.user_ids == ()


# Math


@pytest.mark.parametrize(
    "expr, want",
    [
        ("1+1", "2"),
        ("2*(3+4)", "14"),
        ("2^3^2", "512"),
        ("-2^2", "-4"),
        ("2^-1", "0.5"),
        ("10%3", "1"),
        ("7/2", "3.5"),
        ("--3", "3"),
        ("+3", "3"),
        ("1e3+0.5", "1000.5"),
        ("sqrt(16)+abs(-2)", "6"),
        ("round(2.6)+trunc(-1.5)+sgn(-9)", "1"),
        ("log(1000)+ln(e)+log2(8)", "7"),
        ("pi*0", "0"),
        ("0.1+0.2", "0.30000000000000004"),
        ("2^50", "1125899906842624"),
        ("2^80", "1.2089258196146292e+24"),
    ],
)
def test_math(expr, want):
    assert body(f"{{math:{expr}}}") == want


def test_math_operands_are_blocks():
    assert body("{math:{user(id)}*2}") == "200"
    assert body("{=(n): 4 }{math:{n}^0.5}") == "2"
    assert body("{math:{if(1==1):3|4}+1}") == "4"


@pytest.mark.parametrize("member", ["2*1000", "1+1", "nan", "inf", "1e999", "", "(1)", "x"])
def test_math_member_text_is_one_number(member):
    res = run("{math:{match}+1}", f={"match": member})
    assert res.error == "script_error"


@pytest.mark.parametrize("expr", ["10^400", "1e308*10", "1/0", "1%0", "sqrt(-1)", "ln(0)", "exp(1000)"])
def test_math_errors_stop_the_run(expr):
    res = run(f"{{addrole:1}}{{math:{expr}}}")
    assert res.error == "script_error" and res.plan == ()


@pytest.mark.parametrize(
    "expr, msg",
    [
        ("1+", "ends with an operator"),
        ("(1", "( without a )"),
        ("1)", ") without a ("),
        ("1 2", "need an operator"),
        ("sqrt 4", "needs ( after"),
        ("foo(1)", "Unknown math name"),
        ("1|2", "can't go in math"),
        ("1&2", "can't go in math"),
        ("1" + "+1" * 100, "200 characters"),
        ("(" * 17 + "1" + ")" * 17, "16 levels"),
    ],
)
def test_math_save_errors(expr, msg):
    assert msg in problem(f"{{math:{expr}}}")


def test_math_counts_tokens_as_steps():
    assert run("{math:1+1+1+1+1}").steps == 1 + 9


# Budgets


def test_step_budget():
    tight = make_engine(limits=Limits(steps=10))
    res = tight.run(tight.parse("{addrole:1}" + "{upper:a}" * 20), facts())
    assert res.error == "script_budget" and res.plan == () and "steps" in res.detail


def test_output_characters_cost_steps():
    assert run("x" * 640).steps == 10


def test_deadline():
    slow = make_engine(limits=Limits(deadline_ms=0, clock_every=1))
    res = slow.run(slow.parse("{upper:a}{upper:b}"), facts())
    assert res.error == "script_budget" and "ms" in res.detail


def test_each_condition_costs_a_step():
    src = "{any(" + "|" * 3988 + "):a}"
    assert run(src).steps >= 3989
    tight = make_engine(limits=Limits(steps=100))
    assert tight.run(tight.parse(src), facts()).error == "script_budget"


def test_value_and_work_budgets():
    res = run("{=(a):" + "x" * 3000 + "}{=(b):{a}{a}}")
    assert res.error == "script_budget" and "value" in res.detail
    res = run("{=(a):" + "x" * 2000 + "}" + "{upper:{a}}" * 6)
    assert res.error == "script_budget" and "characters" in res.detail


def test_long_reply_is_cut_and_keeps_actions():
    res = run("{delete}{removerole:<@&7>}" + "R" * 1500 + "{content}", f={"content": "x" * 600})
    assert res.error is None and res.body == "R" * 1500 + "x" * 500
    assert res.plan == ({"kind": "delete"}, {"kind": "role", "op": "remove", "id": "7"})


def test_replace_sizes_before_running():
    res = run("{=(a):" + "a" * 2000 + "}{replace(a,aaa):{a}}")
    assert res.error == "script_budget" and "replace" in res.detail


# Plan


def test_verify_example():
    src = (
        "{stop({hasrole(<@&111>)}):You're already verified.}\n"
        "{addrole:<@&111>}{delete}{deleteafter:10s}\n"
        "Welcome, {user(mention)}! You're verified."
    )
    res = run(src)
    assert res.body == "Welcome, <@100>! You're verified."
    assert res.plan == (
        {"kind": "role", "op": "add", "id": "111"},
        {"kind": "delete"},
        {"kind": "deleteafter", "seconds": 10},
    )
    res = run(src, f={"roles": ["111"]})
    assert (res.body, res.plan, res.stopped) == ("You're already verified.", (), True)


def test_avatar_helper_example():
    src = (
        "{if({channel(id)}==222):{c:avatar {user(id)}}|{reactu:👀}{random:Hi~Hey} "
        "{user(name)}, bot commands go in <#222>.}"
    )
    res = run(src)
    assert (res.body, res.plan) == ("", ({"kind": "command", "text": "avatar 100"},))
    res = run(src, f={"channel": {"id": "9"}})
    assert res.body.endswith("sam, bot commands go in <#222>.")
    assert res.plan == ({"kind": "react", "on": "trigger", "emoji": "👀"},)


def test_kinds_parse_their_targets():
    res = run("{addrole:<@&5>}{removerole: 6 }{react:<:ok:7>}{react:<a:ok_2:8>}{redirect(<#9>)}{message:10}{deleteafter:5m}")
    assert res.plan == (
        {"kind": "role", "op": "add", "id": "5"},
        {"kind": "role", "op": "remove", "id": "6"},
        {"kind": "react", "on": "reply", "emoji": "<:ok:7>"},
        {"kind": "react", "on": "reply", "emoji": "<a:ok_2:8>"},
        {"kind": "redirect", "to": "9"},
        {"kind": "message", "id": "10"},
        {"kind": "deleteafter", "seconds": 300},
    )


@pytest.mark.parametrize(
    "src, msg",
    [
        ("{addrole:admin}", "isn't a role"),
        ("{addrole:{user(id)}}", "needs its role written out"),
        ("{addrole:<@&{match}>}", "needs its role written out"),
        ("{react:ok}", "isn't an emoji"),
        ("{react:<:x:1>}", "isn't an emoji"),
        ("{react:{match}}", "needs its emoji written out"),
        ("{redirect(general)}", "isn't a channel"),
        ("{redirect({channel(id)})}", "needs its channel written out"),
        ("{deleteafter:4s}", "from 5s to 10m"),
        ("{deleteafter:11m}", "from 5s to 10m"),
        ("{deleteafter:soon}", "isn't a time"),
        ("{message:abc}", "isn't an id"),
        ("{delete:now}", "{delete} is written like"),
        ("{addrole}", "{addrole} is written like"),
        ("{addrole:{user(id)}}", "{addrole} needs its role written out. {user(id)} can't give it."),
        ("{c:x {user(name)} }", "{user(name)} can't go in a command."),
        ("{c:x {upper:{user(id)}} }", "{upper:{user(id)}} can't go in a command."),
        ("{c:x{user(id)} }", "{user(id)} must be its own argument"),
    ],
)
def test_targets_must_be_written_out(src, msg):
    assert msg in problem(src)


@pytest.mark.parametrize(
    "emoji",
    ["👀", "❤️", "❤", "👍🏽", "👨‍👩‍👧", "🏳️‍🌈", "🇬🇧", "#️⃣", "1\u20e3", "*\ufe0f\u20e3", "<:ok:7>", "<a:ok_2:8>"],
)
def test_emoji_allowed(emoji):
    assert run(f"{{react:{emoji}}}").plan == ({"kind": "react", "on": "reply", "emoji": emoji},)


@pytest.mark.parametrize(
    "bad",
    [
        "é/../../x", "é?a=b&c", "👀,🙂", "👀🙂", "\u202e", "\u200b", "👀\u200b", "\u200d👀",
        "日本", "#", "1", "ok", "©x", "<:é_x:7>", "🇬",
    ],
)
def test_emoji_refused(bad):
    assert "isn't an emoji" in problem(f"{{react:{bad}}}")


def test_replace_kinds_last_one_wins():
    res = run("{redirect(dm)}{delete}{redirect(<#5>)}{delete}{deleteafter:5s}{deleteafter:6s}")
    assert res.plan == ({"kind": "redirect", "to": "5"}, {"kind": "delete"}, {"kind": "deleteafter", "seconds": 6})


def test_plan_caps_at_run_time():
    res = run("{if(1==1):{c:a}}{if(1==1):{c:b}}")
    assert res.error == "script_budget" and res.plan == ()
    res = run("{react:👀}" * 6)
    assert res.error == "script_budget"
    many = make_engine(limits=Limits(items=2))
    assert many.run(many.parse("{addrole:1}{addrole:2}{addrole:3}"), facts()).error == "script_budget"


# Commands: the security boundary


@pytest.mark.parametrize(
    "src, text",
    [
        ("{c:ping}", "ping"),
        ("{command:avatar {user(id)}}", "avatar 100"),
        ("{c:avatar {user(mention)} big}", "avatar <@100> big"),
        ("{c:info {channel(id)} {server(id)}}", "info 222 333"),
        ("{c:say a\\|b\\:c}", "say a|b:c"),
        ("{c:say a|b}", "say a|b"),
    ],
)
def test_command_allowed(src, text):
    assert run(src).plan == ({"kind": "command", "text": text},)


@pytest.mark.parametrize(
    "src",
    [
        "{c:avatar {match}}",
        "{c:avatar {content}}",
        "{c:avatar {trigger}}",
        "{c:avatar {user(name)}}",
        "{c:avatar {user(display)}}",
        "{c:avatar {channel(name)}}",
        "{c:avatar {channel(mention)}}",
        "{c:avatar {server(name)}}",
        "{c:avatar {hasrole(<@&1>)}}",
        "{=(v):1}{c:avatar {v}}",
        "{c:remind {math:{match}}}",
        "{c:remind {math:1}}",
        "{c:say {upper:{user(id)}}}",
        "{c:say {replace(a,b):{user(id)}}}",
        "{c:say {if(1==1):{user(id)}}}",
        "{c:say {random:{user(id)}~x}}",
        "{c:say {urlencode:{user(id)}}}",
        "{c:{user(id)}}",
        "{c: {user(id)}}",
        "{c:avatar x{user(id)}}",
        "{c:avatar {user(id)}x}",
        "{c:avatar {user(id)}{server(id)}}",
        "{c:" + "x" * 101 + "}",
        "{c:}",
    ],
)
def test_command_refused(src):
    tree = E.parse(src)
    assert not tree.ok
    assert not E.check(tree).ok
    res = E.run(tree, facts())
    assert res.error == "script_error" and res.plan == ()


def test_command_problem_points_at_the_inner_block():
    (p,) = E.parse("hi\n{c:remind {match}}").problems
    assert (p.line, p.col) == (2, 11)


@pytest.mark.parametrize("bad", ["123 456", "<@1>x", "abc", "", "1" * 21, "<@&>", "１２３"])
def test_command_rechecks_ids_at_run_time(bad):
    res = run("{c:avatar {user(id)}}", f={"user": {"id": bad}})
    assert res.error == "script_error" and res.plan == ()


# Checker


def test_check_lists_every_action_in_every_branch():
    src = "{if({match}==a):{c:a {user(id)}}|{random:{addrole:1}~{if(1==2):{redirect(dm)}}}}{stop(1==2):{reactu:👀}}"
    rep = E.check(E.parse(src))
    assert rep.ok, rep.problems
    assert [a.item for a in rep.actions] == [
        {"kind": "command", "text": "a {user(id)}"},
        {"kind": "role", "op": "add", "id": "1"},
        {"kind": "redirect", "to": "dm"},
        {"kind": "react", "on": "trigger", "emoji": "👀"},
    ]
    assert [a.gate for a in rep.actions] == ["premium", None, "basic", None]
    assert (rep.actions[0].line, rep.actions[0].col) == (1, 17)


def test_check_caps_take_the_worst_path():
    assert E.check(E.parse("{if(1==1):{c:a}|{c:b}}")).ok
    assert E.check(E.parse("{random:{c:a}~{c:b}~x}")).ok
    rep = E.check(E.parse("{if(1==1):{c:a}}{c:b}"))
    assert not rep.ok and "2 command actions" in rep.problems[0].message
    assert not E.check(E.parse("{react:👀}" * 3 + "{if(1==1):" + "{react:👀}" * 3 + "}")).ok
    assert E.check(E.parse("{react:👀}" * 3 + "{if(1==1):{react:👀}{react:👀}|" + "{react:👀}" * 2 + "}")).ok
    assert E.check(E.parse("{redirect(dm)}{redirect(<#1>)}")).ok


@pytest.mark.parametrize(
    "src, name",
    [
        ("{REACTU:👀}", "reactu"),
        ("{ reactu :👀}", "reactu"),
        ("{\xa0addrole\xa0:1}", "addrole"),
        ("{command:ping}", "c"),
    ],
)
def test_action_block_is_the_main_name(src, name):
    (action,) = E.check(E.parse(src)).actions
    assert action.block == name


def test_check_user_ids():
    rep = E.check(E.parse("Hi <@1> and <@!2>, not <@&3> or <@x> or <#4>. {if(1==1):<@5>|<@1>}"))
    assert rep.user_ids == ("1", "2", "5")


def test_check_passes_ctx_to_hooks():
    class Picky(Fact):
        def check(self, node, ctx):
            return [f"Not in {ctx['place']}."] if ctx else []

    eng = Engine([Picky(("thing",))])
    rep = eng.check(eng.parse("{thing}"), {"place": "here"})
    assert [p.message for p in rep.problems] == ["Not in here."]
    assert eng.check(eng.parse("{thing}")).ok


def test_check_report_json():
    rep = E.check(E.parse("{addrole:1}{nope}"))
    data = rep.to_json()
    assert data["ok"] is False and data["actions"][0]["item"] == {"kind": "role", "op": "add", "id": "1"}
    assert data["problems"][0]["line"] == 1


# Trace and results


def test_trace():
    res = E.run(E.parse("{=(a):x}{if({a}==x):{upper:{a}}|no}{addrole:1}"), facts(), trace=True)
    steps = [(s.block, s.result) for s in res.trace]
    assert steps == [
        ("{=(a):x}", ""),
        ("{if({a}==x):{upper:{a}}|no}", "true"),
        ("{a}", "x"),
        ("{upper:{a}}", "X"),
        ("{a}", "x"),
        ("{addrole:1}", "planned {'kind': 'role', 'op': 'add', 'id': '1'}"),
    ]
    assert run("{upper:a}").trace is None
    capped = E.run(E.parse("{upper:a}" * 300), facts(), trace=True)
    assert len(capped.trace) == 200


def test_result_json():
    res = run("{addrole:1}hi")
    assert res.to_json() == {
        "v": 1,
        "body": "hi",
        "plan": [{"kind": "role", "op": "add", "id": "1"}],
        "stopped": False,
        "cpu_us": res.cpu_us,
    }
    bad = E.run(E.parse("{nope}"), facts())
    assert bad.to_json()["error"] == "script_error"


def test_run_takes_source_and_never_raises():
    assert E.run("{upper:a}", facts()).body == "A"
    assert E.run("{", facts()).error == "script_error"
    assert E.run("{user(id)}", {}).error is None

    class Broken(Spec):
        names = ("broken",)

        def value(self, node, r):
            raise KeyError("x")

    eng = Engine([Broken()])
    res = eng.run(eng.parse("{broken}"), {})
    assert res.error == "script_error" and "KeyError" in res.detail


def test_run_refuses_a_tree_from_another_engine():
    res = E.run(make_engine().parse("{addrole:1}"), facts())
    assert (res.error, res.detail, res.plan) == ("script_error", "Another engine parsed this script.", ())
    assert Engine().run("{upper:a}", {}).body == "A"


def test_facts_are_not_changed():
    f = facts()
    before = repr(f)
    E.run(E.parse("{=(user):x}{user(id)}{addrole:1}"), f)
    assert repr(f) == before


# Registration and reference


def test_registration():
    eng = Engine()
    assert eng.parse("{upper:a}").ok and not eng.parse("{user(id)}").ok
    eng.register(Fact(("weather",), doc="Today's weather."))
    assert eng.run("{weather}", {"weather": "sunny"}).body == "sunny"
    with pytest.raises(ValueError):
        eng.register(Fact(("WEATHER",)))
    with pytest.raises(ValueError):
        Engine([Fact(("if",))])
    with pytest.raises(TypeError):
        eng.register(object())
    with pytest.raises(ValueError):
        ActionBlock(("x",), "x", field="y")


def test_hints_can_be_extended():
    eng = Engine(hints={"embed": "Use a saved message."})
    assert problem("{embed}", eng) == "{embed} isn't in the Engine. Use a saved message."


def test_reference_lists_each_block_once():
    ref = E.reference()
    names = [r["names"][0] for r in ref]
    assert len(names) == len(set(names))
    assert {"=", "if", "math", "user", "hasrole", "c", "addrole"} <= set(names)
    c = next(r for r in ref if r["names"][0] == "c")
    assert c["names"] == ["c", "command"] and c["gate"] == "premium" and c["category"] == "action"
    assert all(r["example"] for r in ref)


def test_each_example_parses():
    for r in E.reference():
        assert E.parse(r["example"]).ok, r["example"]


# Import rules


ALLOWED = {"__future__", "dataclasses", "typing", "random", "time", "difflib", "math", "urllib.parse"}


def test_engine_imports_only_the_stdlib_it_needs():
    root = pathlib.Path(__file__).parent.parent / "TagScriptEngine" / "engine"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [] if node.level else [node.module]
            else:
                continue
            for mod in mods:
                assert mod in ALLOWED, f"{path.name} imports {mod}"


def test_version():
    import TagScriptEngine

    assert TagScriptEngine.__version__ == "2.8.0"
    assert TagScriptEngine.Engine is Engine


def test_engine_loads_on_first_use():
    code = (
        "import sys, TagScriptEngine as t\n"
        "assert 'TagScriptEngine.engine' not in sys.modules\n"
        "assert t.Engine.__module__ == 'TagScriptEngine.engine'\n"
        "assert not hasattr(t, 'Nope')\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd=pathlib.Path(__file__).parent.parent)
