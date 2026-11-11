"""Structural math: operators and numbers come only from the script's own text.

Each block inside an expression is one operand. Everything is a float, and a result that
isn't finite is an error, so no step can run unbounded.
"""

from __future__ import annotations

import math as _m

from .parse import Block, Sep

__all__ = ("compile_math", "MathError", "format_number")


class MathError(Exception):
    pass


def _sgn(x: float) -> float:
    return (x > 0) - (x < 0)


FUNCS = {
    "sin": _m.sin,
    "cos": _m.cos,
    "tan": _m.tan,
    "exp": _m.exp,
    "abs": abs,
    "trunc": lambda x: float(_m.trunc(x)),
    "round": lambda x: float(round(x)),
    "sgn": _sgn,
    "log": _m.log10,
    "ln": _m.log,
    "log2": _m.log2,
    "sqrt": _m.sqrt,
}
CONSTS = {"pi": _m.pi, "e": _m.e}
BINARY = {"+": (1, False), "-": (1, False), "*": (2, False), "/": (2, False), "%": (2, False)}
BINARY["^"] = (4, True)
NEG = (3, True)
OPEN = "("


def _apply(op: str, a: float, b: float) -> float:
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            raise MathError("Division by zero.")
        return a / b
    if op == "%":
        if b == 0:
            raise MathError("Division by zero.")
        return _m.fmod(a, b)
    return _m.pow(a, b)


def _tokens(parts: tuple, err) -> list | None:
    """Split literal text into numbers, names and operators. A Block is one operand."""
    out: list = []
    for part in parts:
        if isinstance(part, Block):
            out.append(part)
            continue
        if isinstance(part, Sep):
            err(f"{part.char} can't go in math.")
            return None
        s, i, n = part, 0, len(part)
        while i < n:
            c = s[i]
            if c.isspace():
                i += 1
            elif c.isdigit() or c == ".":
                j = i
                while j < n and (s[j].isdigit() or s[j] == "."):
                    j += 1
                if j < n and s[j] in "eE":
                    k = j + 1
                    if k < n and s[k] in "+-":
                        k += 1
                    if k < n and s[k].isdigit():
                        j = k
                        while j < n and s[j].isdigit():
                            j += 1
                try:
                    out.append(float(s[i:j]))
                except ValueError:
                    err(f"{s[i:j]} isn't a number.")
                    return None
                i = j
            elif c.isalpha():
                j = i
                while j < n and (s[j].isalnum()):
                    j += 1
                word = s[i:j].lower()
                if word not in FUNCS and word not in CONSTS:
                    err(f"Unknown math name {s[i:j]}.")
                    return None
                out.append(("name", word))
                i = j
            elif c in "+-*/%^()":
                out.append(c)
                i += 1
            else:
                err(f"{c} can't go in math.")
                return None
    return out


def compile_math(parts: tuple, err, *, chars: int, depth: int) -> tuple | None:
    """Shunting-yard into postfix. Items: float, Block, an operator str, ("neg",) or ("fn", name)."""
    size = sum(1 if isinstance(p, Block) else len(p.char if isinstance(p, Sep) else p) for p in parts)
    if size > chars:
        err(f"Math is limited to {chars} characters.")
        return None
    toks = _tokens(parts, err)
    if toks is None:
        return None
    if not toks:
        err("This math is empty.")
        return None
    out: list = []
    ops: list = []
    expect_operand = True
    level = 0
    after_fn = False
    for t in toks:
        if after_fn and t != "(":
            err("A math function needs ( after its name.")
            return None
        after_fn = isinstance(t, tuple) and t[1] in FUNCS
        if isinstance(t, (float, Block)) or (isinstance(t, tuple) and t[1] in CONSTS):
            if not expect_operand:
                err("Two numbers need an operator between them.")
                return None
            out.append(CONSTS[t[1]] if isinstance(t, tuple) else t)
            expect_operand = False
        elif isinstance(t, tuple):
            if not expect_operand:
                err("Two numbers need an operator between them.")
                return None
            ops.append(("fn", t[1]))
        elif t == "(":
            if not expect_operand:
                err("Two numbers need an operator between them.")
                return None
            level += 1
            if level > depth:
                err(f"Math is limited to {depth} levels of brackets.")
                return None
            ops.append(OPEN)
        elif t == ")":
            if expect_operand:
                err("Math has an empty () or ends with an operator.")
                return None
            while ops and ops[-1] != OPEN:
                out.append(ops.pop())
            if not ops:
                err("Math has a ) without a (.")
                return None
            ops.pop()
            level -= 1
            if ops and isinstance(ops[-1], tuple) and ops[-1][0] == "fn":
                out.append(ops.pop())
        elif expect_operand:
            if t == "-":
                ops.append(("neg",))
            elif t != "+":
                err(f"Math has {t} where a number should be.")
                return None
        else:
            prec, right = BINARY[t]
            while ops:
                top = ops[-1]
                if top == OPEN or (isinstance(top, tuple) and top[0] == "fn"):
                    break
                tprec = NEG[0] if isinstance(top, tuple) else BINARY[top][0]
                if tprec > prec or (tprec == prec and not right):
                    out.append(ops.pop())
                else:
                    break
            ops.append(t)
            expect_operand = True
    if expect_operand:
        err("Math ends with an operator.")
        return None
    while ops:
        top = ops.pop()
        if top == OPEN:
            err("Math has a ( without a ).")
            return None
        if isinstance(top, tuple) and top[0] == "fn":
            err("A math function needs ( after its name.")
            return None
        out.append(top)
    return tuple(out)


def evaluate(rpn: tuple, operand, spend) -> float:
    """``operand(block)`` gives a block's number. ``spend(n)`` charges steps."""
    spend(len(rpn))
    stack: list[float] = []
    try:
        for item in rpn:
            if isinstance(item, float):
                stack.append(item)
            elif isinstance(item, Block):
                stack.append(operand(item))
            elif isinstance(item, str):
                b = stack.pop()
                stack.append(_apply(item, stack.pop(), b))
            elif item[0] == "neg":
                stack.append(-stack.pop())
            else:
                stack.append(float(FUNCS[item[1]](stack.pop())))
            if not _m.isfinite(stack[-1]):
                raise MathError("The result is too big.")
    except (OverflowError, ZeroDivisionError):
        raise MathError("The result is too big.") from None
    except ValueError:
        raise MathError("That math has no answer.") from None
    return stack[-1]


def to_number(text: str) -> float:
    try:
        x = float(text.strip())
    except ValueError:
        raise MathError(f"Math needs a number, not {text[:40]!r}.") from None
    if not _m.isfinite(x):
        raise MathError(f"Math needs a number, not {text[:40]!r}.")
    return x


def format_number(x: float) -> str:
    """Whole numbers print as ``2``."""
    if x.is_integer() and abs(x) < 1e16:
        return str(int(x))
    return repr(x)
