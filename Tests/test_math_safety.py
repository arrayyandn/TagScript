import random
import sys
import threading
import time
import unittest

from TagScriptEngine import Interpreter, block


class TestMathGuards(unittest.TestCase):
    def setUp(self):
        self.engine = Interpreter([block.MathBlock(), block.RangeBlock()])

    def run_math(self, expr):
        return self.engine.process("{math:%s}" % expr).body

    def test_freeze_case_is_fast_and_prints_as_written(self):
        for expr in ("trunc(3)^trunc(1e7)", "trunc(3)^trunc(1e6)", "trunc(2)^trunc(1e300)"):
            start = time.perf_counter()
            self.assertEqual(self.run_math(expr), "{math:%s}" % expr)
            self.assertLess(time.perf_counter() - start, 0.2, expr)

    def test_pow_edge_cases_match_2_6_2(self):
        cases = {
            "1^1e9": "1.0",
            "trunc(1)^trunc(1e9)": "1",
            "trunc(-1)^trunc(1e9)": "1",
            "trunc(-1)^trunc(1e9+1)": "-1",
            "trunc(0)^trunc(1e9)": "0",
            "trunc(0)^trunc(0)": "1",
            "trunc(2)^trunc(-3)": "0.125",
            "trunc(2)^0.5": "1.4142135623730951",
            "trunc(2)^trunc(3)^trunc(2)": "512",
            "trunc(trunc(2)^trunc(10))^trunc(3)": "1073741824",
            "trunc(10)^trunc(4299)": "1" + "0" * 4299,
            "trunc(-10)^trunc(4299)": "-1" + "0" * 4299,
        }
        for expr, expect in cases.items():
            self.assertEqual(self.run_math(expr), expect, expr)

    def test_pow_failures_still_print_as_written(self):
        for expr in (
            "trunc(10)^trunc(4300)",
            "2^trunc(1e7)",
            "trunc(2)^1e7",
            "trunc(0)^trunc(-1)",
            "trunc(2)^trunc(trunc(10)^trunc(400))",
        ):
            self.assertEqual(self.run_math(expr), "{math:%s}" % expr, expr)

    def test_multiply_guard(self):
        self.assertEqual(self.run_math("trunc(1e300)*trunc(1e300)"), str(int(1e300) ** 2))
        big = "trunc(10)^trunc(3000)"
        self.assertEqual(self.run_math(f"{big}*{big}"), "{math:%s*%s}" % (big, big))
        # Accepted change: a middle step over 4,300 digits now refuses the whole block.
        self.assertEqual(self.run_math(f"log({big}*{big})"), "{math:log(%s*%s)}" % (big, big))


class TestMathThreads(unittest.TestCase):
    def test_threads_get_correct_results(self):
        engine = Interpreter([block.MathBlock()])
        exprs = {f"{i}*{i}+{i}-(1+{i})/2": str(i * i + i - (1 + i) / 2) for i in range(1, 9)}
        wrong = []

        def worker(expr, expect):
            for _ in range(300):
                got = engine.process("{math:%s}" % expr).body
                if got != expect:
                    wrong.append((expr, got))

        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        try:
            threads = [threading.Thread(target=worker, args=item) for item in exprs.items()]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            sys.setswitchinterval(old)
        self.assertEqual(wrong, [])


class TestRangeSeed(unittest.TestCase):
    def setUp(self):
        self.engine = Interpreter([block.RangeBlock()])

    def test_seeded_values_match_2_6_2(self):
        cases = {
            "{range(abc):1-1000}": "791",
            "{range(seed):1-6}{range(seed):1-6}": "22",
            "{range(1.5):0-99999}": "40990",
            "{range(x):10-1}": "{range(x):10-1}",
        }
        for script, expect in cases.items():
            self.assertEqual(self.engine.process(script).body, expect, script)

    def test_seeded_random_picks(self):
        engine = Interpreter([block.RandomBlock()])
        items = ["a", "b", "c", "d", "e"]
        for seed in ("abc", "1", "seed", "long seed"):
            expect = random.Random(seed).choice(items)
            self.assertEqual(engine.process("{random(%s):a,b,c,d,e}" % seed).body, expect, seed)
            self.assertEqual(engine.process("{random(%s):a~b~c~d~e}" % seed).body, expect, seed)

    def test_seeded_random_threads(self):
        engine = Interpreter([block.RandomBlock()])
        items = [str(i) for i in range(50)]
        script = "{random(%s):" + ",".join(items) + "}"
        wrong = []

        def worker(seed):
            expect = random.Random(seed).choice(items)
            for _ in range(200):
                got = engine.process(script % seed).body
                if got != expect:
                    wrong.append((seed, got))

        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        try:
            threads = [threading.Thread(target=worker, args=(f"s{i}",)) for i in range(32)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            sys.setswitchinterval(old)
        self.assertEqual(wrong, [])

    def test_does_not_reseed_global_random(self):
        random.seed(7)
        expect = random.random()
        random.seed(7)
        self.engine.process("{range(abc):1-1000}")
        self.assertEqual(random.random(), expect)


if __name__ == "__main__":
    unittest.main()
