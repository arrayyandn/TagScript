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

## Engine (2.7.0, opt-in)

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
`{random}`, `{math}`, `{replace}`, `{upper}`, `{lower}`, `{urlencode}`, `{stop}`, `{break}`.

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
  blocks the Engine leaves out (`cooldown`, `require`, `embed`, `python`, `range` and others)
  and old short names (`m`, `calc`, `+`, `or`, `and`, `#`) say what to use instead. Variables
  hold one text value, so `{a(1)}` on a variable is a save error, not a list item.
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

## Dependencies

`Python 3.12+`

`discord.py`

`pyparsing`
