import ast
import math
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.errors import SchemaViolation
from app.core.time import utcnow
from app.core.tokens import estimate_tokens


class CalculatorArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(min_length=1, max_length=100)


class WordStatsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)


class UtcNowArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


def safe_calc(expression: str) -> int | float:
    """Evaluate arithmetic without eval. Only numbers and + - * / ( )."""
    if len(expression) > 100:
        raise ValueError("expression is too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("expression is not valid arithmetic") from exc
    value = _eval_node(tree.body)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueError("result is not a finite number")
    if abs(value) > 1_000_000_000_000:
        raise ValueError("result is out of range")
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _eval_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if right == 0:
            raise ValueError("division by zero")
        return left / right
    raise ValueError("expression may only use numbers and + - * /")


def _calculator(args: CalculatorArgs) -> dict[str, object]:
    return {"expression": args.expression, "value": safe_calc(args.expression)}


def _utc_now(_args: UtcNowArgs) -> dict[str, str]:
    return {"utc": utcnow().isoformat() + "Z"}


def _word_stats(args: WordStatsArgs) -> dict[str, int]:
    return {
        "characters": len(args.text),
        "words": len(args.text.split()),
        "estimated_tokens": estimate_tokens(args.text),
    }


def _specs() -> dict[str, tuple[str, type[BaseModel], Callable[[BaseModel], dict[str, object]]]]:
    return {
        "calculator": (
            "Evaluate arithmetic using numbers and + - * / and parentheses.",
            CalculatorArgs,
            _calculator,
        ),
        "utc_now": (
            "Return the current UTC time.",
            UtcNowArgs,
            _utc_now,
        ),
        "word_stats": (
            "Count characters, words, and estimated tokens in a string.",
            WordStatsArgs,
            _word_stats,
        ),
    }


def tool_catalog() -> list[dict[str, str]]:
    return [
        {"name": name, "description": description}
        for name, (description, _model, _handler) in _specs().items()
    ]


def run_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
    spec = _specs().get(name)
    if spec is None:
        raise SchemaViolation(f"Unknown tool '{name}'.")
    _description, args_model, handler = spec
    try:
        parsed = args_model.model_validate(arguments)
    except ValidationError as exc:
        raise SchemaViolation(f"Arguments for '{name}' are invalid.") from exc
    try:
        result = handler(parsed)
    except ValueError as exc:
        raise SchemaViolation(str(exc)) from exc
    if not isinstance(result, dict):
        raise SchemaViolation(f"Tool '{name}' returned an unexpected result.")
    return result
