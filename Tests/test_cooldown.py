import json
import unittest

from TagScriptEngine import AsyncInterpreter, Interpreter, adapter, block
from TagScriptEngine.exceptions import CooldownExceeded
from TagScriptEngine.interpreter import Context, Response
from TagScriptEngine.verb import Verb


def get_blocks(defer: bool):
    return [
        block.AssignmentBlock(),
        block.StrictVariableGetterBlock(),
        block.LooseVariableGetterBlock(),
        block.CooldownBlock(defer=defer),
    ]


class TestDeferredCooldown(unittest.TestCase):
    def setUp(self):
        self.engine = Interpreter(get_blocks(True))
        self.seed = {"author": adapter.StringAdapter("741074175875088424")}

    def tearDown(self):
        self.engine = None

    def process(self, script: str):
        return self.engine.process(script, self.seed, cooldown_key="1:tag")

    def test_appends_entry(self):
        response = self.process("before {cooldown(2|10.5):{author}} after")
        self.assertEqual(response.body, "before  after")
        self.assertEqual(
            response.actions["cooldowns"],
            [{"key": "741074175875088424", "rate": 2, "per": 10.5, "message": None}],
        )
        self.assertIsInstance(response.actions["cooldowns"][0]["rate"], int)
        self.assertIsInstance(response.actions["cooldowns"][0]["per"], float)

    def test_never_raises_or_stores(self):
        before = dict(block.CooldownBlock.COOLDOWNS)
        for _ in range(5):
            response = self.process("{cooldown(1|60):same}hi")
            self.assertEqual(response.body, "hi")
            self.assertEqual(len(response.actions["cooldowns"]), 1)
        self.assertEqual(block.CooldownBlock.COOLDOWNS, before)

    def test_multiple_in_order(self):
        script = "{cooldown(1|5):a}{cooldown(3|60):b|slow {key}}{cooldown(1|5):a}"
        response = self.process(script)
        self.assertEqual(response.body, "")
        self.assertEqual(
            response.actions["cooldowns"],
            [
                {"key": "a", "rate": 1, "per": 5.0, "message": None},
                {"key": "b", "rate": 3, "per": 60.0, "message": "slow b"},
                {"key": "a", "rate": 1, "per": 5.0, "message": None},
            ],
        )

    def test_custom_message(self):
        script = "{cooldown(1|10):{author}|{key} wait **{retry_after}**s ({key})}"
        response = self.process(script)
        self.assertEqual(
            response.actions["cooldowns"][0]["message"],
            "741074175875088424 wait **{retry_after}**s (741074175875088424)",
        )

    def test_message_uses_variables(self):
        script = "{=(name):Tag}{cooldown(1|10):k|{name} is on cooldown for {retry_after}s}"
        response = self.process(script)
        self.assertEqual(
            response.actions["cooldowns"][0]["message"],
            "Tag is on cooldown for {retry_after}s",
        )

    def test_empty_message_is_default(self):
        response = self.process("{cooldown(1|10):k|}")
        self.assertEqual(response.actions["cooldowns"][0]["message"], None)

    def test_invalid_params(self):
        scripts = (
            "{cooldown(1.5|10):k}",
            "{cooldown(a|10):k}",
            "{cooldown(1|a):k}",
            "{cooldown(0|10):k}",
            "{cooldown(-1|10):k}",
            "{cooldown(1|0):k}",
            "{cooldown(1|-5):k}",
            "{cooldown(1|inf):k}",
            "{cooldown(1|nan):k}",
            "{cooldown(1):k}",
            "{cooldown(1|2|3):k}",
            "{cooldown:k}",
            "{cooldown(1|10)}",
        )
        for script in scripts:
            with self.subTest(script=script):
                response = self.process(script)
                self.assertEqual(response.body, script)
                self.assertNotIn("cooldowns", response.actions)

    def test_json_round_trip(self):
        response = self.process("{cooldown(2|3):{author}|{key}: {retry_after}}{cooldown(1|1):x}")
        actions = json.loads(json.dumps(response.actions, allow_nan=False))
        self.assertEqual(actions, response.actions)


class TestDeferredCooldownAsync(unittest.IsolatedAsyncioTestCase):
    async def test_retry_after_survives(self):
        engine = AsyncInterpreter(get_blocks(True))
        seed = {"author": adapter.StringAdapter("123")}
        script = "{=(name):Tag}{cooldown(1|2.5):{author}|{name} {key} {retry_after}}"
        response = await engine.process(script, seed, cooldown_key="1:tag")
        self.assertEqual(response.body, "")
        self.assertEqual(
            response.actions["cooldowns"],
            [{"key": "123", "rate": 1, "per": 2.5, "message": "Tag 123 {retry_after}"}],
        )


class TestLegacyCooldown(unittest.TestCase):
    def setUp(self):
        self.engine = Interpreter(get_blocks(False))

    def tearDown(self):
        block.CooldownBlock.COOLDOWNS.pop("legacy:test", None)
        self.engine = None

    def test_raises_after_rate(self):
        script = "before {cooldown(1|10):k|{key} wait {retry_after}} after"
        first = self.engine.process(script, cooldown_key="legacy:test")
        self.assertEqual(first.body, "before  after")
        self.assertEqual(first.actions, {})

        second = self.engine.process(script, cooldown_key="legacy:test")
        self.assertTrue(second.body.startswith("before k wait "))
        self.assertNotIn("after", second.body)
        self.assertNotIn("{retry_after}", second.body)
        self.assertEqual(second.actions, {})

    def test_exception_details(self):
        cooldown = block.CooldownBlock()
        script = "{cooldown(1|10):k}"
        self.engine.process(script, cooldown_key="legacy:test")
        response = Response(extra_kwargs={"cooldown_key": "legacy:test"})
        with self.assertRaises(CooldownExceeded) as cm:
            cooldown.process(Context(Verb(script), response, self.engine, script))
        self.assertEqual(cm.exception.key, "k")
        self.assertTrue(cm.exception.message.startswith("The bucket for k has reached"))

    def test_legacy_parsing(self):
        # legacy mode keeps parsing rate as a decimal and per as a whole number
        response = self.engine.process("{cooldown(1.5|10):k}", cooldown_key="legacy:test")
        self.assertEqual(response.body, "")
        response = self.engine.process("{cooldown(1|2.5):k}", cooldown_key="legacy:test")
        self.assertEqual(response.body, "{cooldown(1|2.5):k}")
