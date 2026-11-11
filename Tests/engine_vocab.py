"""A test vocabulary that mirrors design §5's facts and actions. Element registers the real one."""

from TagScriptEngine.engine import (
    COMMAND,
    DURATION,
    EMOJI,
    ROLE,
    SNOWFLAKE,
    TARGET,
    ActionBlock,
    Engine,
    Fact,
)

FACTS = (
    Fact(
        ("user",),
        params=("id", "mention", "name", "display", "joined", "created"),
        ids=("id", "mention"),
        doc="The member who sent the message.",
    ),
    Fact(("channel",), params=("id", "name", "mention"), ids=("id",), doc="The channel."),
    Fact(("server",), params=("id", "name"), ids=("id",), doc="The server."),
    Fact(("trigger",), doc="The trigger's text."),
    Fact(("match",), read=lambda f, p: f.get("match", "")[:100], doc="The matched text."),
    Fact(("content",), read=lambda f, p: f.get("content", "")[:1000], doc="The message."),
    Fact(
        ("hasrole",),
        params=ROLE,
        read=lambda f, role: "true" if role in f.get("roles", ()) else "false",
        example="{hasrole(<@&111>)}",
        doc="true if the member has the role.",
    ),
)

ACTIONS = (
    ActionBlock(
        ("redirect",), "redirect", arg=TARGET, field="to", where="param", replace=True,
        example="{redirect(dm)}", gate="basic",
    ),
    ActionBlock(("react",), "react", arg=EMOJI, field="emoji", fields={"on": "reply"}, example="{react:👀}"),
    ActionBlock(("reactu",), "react", arg=EMOJI, field="emoji", fields={"on": "trigger"}, example="{reactu:👀}"),
    ActionBlock(("addrole",), "role", arg=ROLE, field="id", fields={"op": "add"}, example="{addrole:<@&111>}"),
    ActionBlock(
        ("removerole",), "role", arg=ROLE, field="id", fields={"op": "remove"}, example="{removerole:<@&111>}"
    ),
    ActionBlock(("delete",), "delete", replace=True),
    ActionBlock(
        ("deleteafter",), "deleteafter", arg=DURATION, field="seconds", replace=True, example="{deleteafter:10s}"
    ),
    ActionBlock(("message",), "message", arg=SNOWFLAKE, field="id", example="{message:123}"),
    ActionBlock(
        ("c", "command"), "command", arg=COMMAND, field="text", example="{c:avatar {user(id)}}", gate="premium"
    ),
)


def make_engine(**kw) -> Engine:
    return Engine((*FACTS, *ACTIONS), **kw)


def facts(**over) -> dict:
    base = {
        "user": {
            "id": "100",
            "mention": "<@100>",
            "name": "sam",
            "display": "Sam",
            "joined": "2024-01-01",
            "created": "2020-01-01",
        },
        "channel": {"id": "222", "name": "welcome", "mention": "<#222>"},
        "server": {"id": "333", "name": "Book Club"},
        "trigger": "verify",
        "match": "verify",
        "content": "verify",
        "roles": [],
    }
    base.update(over)
    return base
