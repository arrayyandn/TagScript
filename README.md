## Information
<a href='https://tagscript.readthedocs.io/en/latest/?badge=latest'>
    <img src='https://readthedocs.org/projects/tagscript/badge/?version=latest' alt='Documentation Status' />
</a>
<a href='https://pypi.python.org/pypi/TagScript/'>
    <img src='https://img.shields.io/pypi/v/TagScript' alt=' yPI' />
</a>

This repository is a fork of JonSnowbd's [TagScript](https://github.com/JonSnowbd/TagScript), a string templating language.
This fork adds support for Discord object adapters and a couple Discord related blocks, as
well as multiple utility blocks. Additionally, several tweaks have been made to the engine's
behavior.

This TagScriptEngine is used on [Noumenon, a Discord bot](https://discordapp.com/oauth2/authorize?client_id=634866217764651009&permissions=2080894207&scope=bot%20applications.commands).
An example implementation can be found its [Tags cog](https://github.com/phenom4n4n/phen-cogs/tree/master/tags).

Additional documentation on the TagScriptEngine library can be [found here](https://tagscript.readthedocs.io/en/latest/).

## Installation

Download the latest version through pip:

```
pip(3) install TagScript
```

Download from a commit:

```
pip(3) install git+https://github.com/phenom4n4n/TagScript.git@<COMMIT_HASH>
```

Install for editing/development:

```
git clone https://github.com/phenom4n4n/TagScript.git
pip(3) install -e ./TagScript
```

## What?

TagScript is a drop in easy to use string interpreter that lets you provide users with ways of
customizing their profiles or chat rooms with interactive text.

For example TagScript comes out of the box with a random block that would let users provide
a template that produces a new result each time its ran, or assign math and variables for later
use.

## Engine (opt-in, since 2.7.0)

`tse.Engine` is a second, stricter way to run TagScript, built for scripts that members of a
server write and other members trigger. The legacy `Interpreter` is unchanged and still the
default. `TagScriptEngine/engine/` uses only the standard library and imports neither pyparsing
nor discord.py, but the package as a whole still needs both (see Dependencies). The Engine loads
on first use of `tse.Engine`, so the legacy `Interpreter` never imports it.

```python
import TagScriptEngine as tse
from TagScriptEngine.engine import ROLE, ActionBlock, Fact

engine = tse.Engine([
    Fact(("user",), params=("id", "mention", "name"), ids=("id", "mention")),
    # facts["roles"] is a set of the member's role ids, as str: {"111", "222"}
    Fact(("hasrole",), params=ROLE, read=lambda facts, role: str(role in facts["roles"]).lower()),
    ActionBlock(("addrole",), "role", arg=ROLE, field="id", fields={"op": "add"}),
])

tree = engine.parse(src)          # immutable tree, problems carry line and column
report = engine.check(tree)       # problems, every action in every branch, user ids
result = engine.run(tree, facts)  # body, plan, stopped, steps, cpu_us
result.to_json()  # {"v": 1, "body": ..., "plan": [...], "stopped": false, "cpu_us": ...}
```

- `parse(src)` never raises. `tree.ok` is false when there are save errors, such as an unknown
  block (`Unknown block {uper}. Did you mean {upper}?`). It lists at most 50 problems, then one
  that says there are more.
- `check(tree, ctx=None)` lists each action block by its main name, with its plan item, gate,
  line and column, and adds a problem when a script could plan more than the caps on any one
  path. `report.user_ids` are the user ids written anywhere in the script (`<@id>` mentions, in
  the reply, conditions or command text). Each block's `check(node, ctx)` hook can add its own
  problems, for example for a role the bot can't manage.
- `run(tree, facts, *, trace=False, rng=None)` never raises. Facts are plain data and are never
  changed. On a parse error, budget hit or exception, `result.error` is `"script_error"` or
  `"script_budget"` and there is no plan. A tree parsed by another engine is a `"script_error"`.
  `trace=True` records up to 200 block results.
- `result.cpu_us` is CPU time for the run only, not parse or check, and is coarse on Windows (0
  or 15,625). Time parse, check and run yourself when you need a real number.
- `engine.register(*specs)` adds blocks. `Fact` reads a value, `ActionBlock` adds one typed item
  to the plan when it runs and prints nothing, and `Spec` is the base for anything else.
  `engine.reference()` lists every block with its doc and example.
- `Engine(limits=Limits(...))` overrides any cap.

Built in: `{=(name):value}` (also `let`, `assign`), `{name}`, `{if}`, `{any}`, `{all}`,
`{random}`, `{math}`, `{replace}`, `{upper}`, `{lower}`, `{urlencode}`, `{in}`, `{contains}`,
`{index}`, `{substr}`, `{stop}`, `{break}`.

Example, with Element's vocabulary:

```
{stop({hasrole(<@&111>)}):You're already verified.}
{addrole:<@&111>}{delete}{deleteafter:10s}
Welcome, {user(mention)}! You're verified.
```

```
{if({channel(id)}==222):{c:avatar {user(id)}}|{reactu:👀}{random:Hi~Hey} {user(name)}, bot commands go in <#222>.}
```

### How the Engine differs from the Interpreter

- **Member text is never code.** The script is parsed once into a tree, and values are never
  parsed again. Text from a fact or a variable can't add a branch, an operator, a `~` or `,`
  option, a block or a command argument. `{if({match}==secret):yes|no}` with a member typing
  `x!=y` or `true):PWNED|` answers `no`.
- **Names are written out.** `{{match}}` is a save error, not a block named by the member.
- **Unknown blocks are save errors** with a "did you mean", instead of printing as text. Legacy
  blocks the Engine leaves out (`cooldown`, `require`, `embed`, `range`, `strf` and others)
  and old names (`m`, `calc`, `+`, `or`, `and`, `#`, `halt`, `short`, `?`, `substring` and
  others) say what to use instead. Variables hold one text value, so `{a(1)}` on a variable is
  a save error, not a list item.
- **`{in}`, `{contains}`, `{index}` and `{substr}`** give legacy's answers, and member text in
  them stays text. An empty `()` or empty text written in the script is a save error. `{substr}` takes
  `(start)` or `(start-end)` and cuts decimals to whole numbers, as legacy does. `-` is the
  separator, so there are no negative numbers. A start or end that isn't a number, or more than
  two numbers, is a save error when written in the script and a `"script_error"` when it comes
  from a block, as in `{math}`. Legacy printed the block as written, or used the first two.
- **Branches are lazy.** `if`, `any`, `all` and `random` run only the branch they pick, so only
  its actions are planned. `any` and `all` stop at the first answer. `if`, `any` and `all` take
  at most two branches.
- **Conditions** use the operators written in the script. A condition splits at the first
  operator found in this order: `!=`, `==`, `>=`, `<=`, `>`, `<`, not at the first one written,
  so `a<b==c` compares `a<b` with `c`. `==` and `!=` compare text. `<`, `>`, `<=` and `>=` need
  a finite number on each side, and when a side isn't one (a member typing `seventeen`), the run
  ends with `"script_error"` and no plan, as `{math}` does. That only happens to a condition the
  run reaches, so a branch not taken, or an `any` or `all` that already has its answer, is fine.
- **Escapes print the character**: `\{ \} \| \: \( \) \~ \, \\`.
- **Math** is parsed with the script. Each block inside it is one number, so a member can't add
  operators. Numbers are floats, whole numbers print as `2`, and a result too big for a float is
  an error. The block is `{math}` only, at most 200 characters and 16 levels of brackets.
- **Actions are planned, not done.** Blocks never touch Discord. A run returns a typed plan, and
  only for a run that finishes cleanly. `{stop}` drops the whole plan, `{redirect}` too, so its
  own text is posted in the channel. `{break}` keeps the reply so far, needs no condition and
  takes no text. `{break}` can't go inside `{stop}`, so a stop always wins.
- **Targets are written out.** Roles, emoji, channels, durations and message ids take literal
  text only. A command takes fixed text plus id facts such as `{user(id)}`, each with spaces
  around it, and each id is checked again when the script runs.
- **Budgets.** Defaults: 4,000 characters, 1,000 blocks and 32 levels per script; 5,000 steps
  and a 20 ms deadline per run; 4,000 characters per value, 20,000 characters of output work and
  a 2,000 character reply; 12 plan items, with at most 1 command, 5 reactions, 5 role changes and
  1 saved message. A longer reply is cut to 2,000 characters, as tags do, and keeps its plan.
  Hitting any other cap above ends the run with no plan. The parser and math are iterative, so deep nesting
  can't overflow the stack.

### Legacy options (opt-in, since 2.8.0)

For old scripts, `Engine(...)` takes these, all off by default. With none of them on, the
Engine works as above.

- `builtins=BUILTINS`: the text and control blocks to start from. Leave one out to register
  your own under its name, as in `builtins=[b for b in BUILTINS if "if" not in b.names]`.
- `loose=True`: unknown names, unset variables, old names, stray braces, blocks of the wrong
  shape and `{` with no `}` print as written, as legacy prints them, and the blocks inside them
  still run in place. So do `{math}` and `{substr}` written with a sum or bounds the Engine can't
  read (legacy still reads `{substr(1-2-3):...}` and an empty `{substr(1):}`), and `{in}`, `{contains}` and `{index}` answer for an empty part like legacy. Each is a warning,
  so `tree.ok` stays true, until there are more than `Limits.problems` of them: past that cap the
  tree gets an error. Names match like legacy: facts and variables by their exact case, other
  blocks in any case, and a name with spaces around it is nothing. Budgets, the depth cap and
  every other save error still fail, and so does a run where a member's text makes `{math}` or
  `{substr}` unreadable (`script_error`). Printed text is never parsed again, so `check` still
  lists every action that can run.
- `legacy_stop=True`: `{stop(...):text}` keeps the reply before it and the actions planned so
  far. It needs a condition, so `{stop}` and `{stop:x}` are the wrong shape.
- `legacy_break=True`: `{break(...):text}` makes `text` the whole reply and the run goes on, so
  later actions are planned. A later `{break}` wins, and a `{break}` reply wins over a `{stop}`.
- `shadow_facts=True`: `{=(args):...}` makes `{args}` read the variable. Only facts can be
  shadowed, never actions or other blocks. A shadowed fact can't go in a command: it is a save
  error, and the run fails too if a variable set some other way shadows it. Override
  `Fact.shadow(value, param)` to read `{args(2)}` from the variable, and put `None` in a fact's
  `params` to let `{args}` go without one.

If you replace `{=}` through `builtins`, the new block must subclass `Assign`, and a new
`{break}` must subclass `Break`, or the save checks above can't see them. A custom `bind`
passed to `parse()` now also gets `kids` and `bad`. A custom `Kind` whose `parse` returns `None`
without raising is now a save error ("got no ..."), even with no options on, because `check`
could not list that action. The built-in kinds never do this.

Still not legacy, with every option on:

- Branches stay lazy. A `{stop}`, `{break}`, `{=}` or action in a branch not taken never runs,
  so `{if(1==1):{=(r):a}|{=(r):b}}{r}` gives `a` (legacy: `b`), and a block in it prints as
  written in the text before a stop.
- An `if` with no operator is false: `{if({args}):yes|no}` gives `no`, where legacy prints it as
  written.
- A block name made by other blocks prints as written: `{=(n):user}{{n}}` gives `{user}`
  (legacy: `sam`).
- Member text and variable values are never read as script, so `==`, `!=` or `|` in them is
  never an operator or a separator. `{if({args}==):none|some}` with args `x==x` gives `some`
  (legacy: `none`), and a `{stop}` on such text can differ the same way.
- Legacy stores and reads variable names by their exact text, spaces included. The Engine trims
  them: `{=( x ):1}{x}` gives `1` (legacy: `{x}`), and `{=(x ):1}{x }` prints `{x }` (legacy: `1`).
- Escapes, `{x(2)}` on a variable, errors from other strict blocks (three `if` branches, a bad
  variable name, a command), text after `)`, and the `short` and `halt` names stay as above.
  `{=(x)}` stores nothing, not `None`, and `{break}` with no condition is the wrong shape
  instead of a crash.

## Dependencies

`Python 3.12+`

`discord.py`

`pyparsing`
