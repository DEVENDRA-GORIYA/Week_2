import pytest

from app.core.errors import SchemaViolation
from app.core.tokens import estimate_tokens
from app.prompts.json_utils import extract_json_object
from app.tools.registry import run_tool


def test_calculator_accepts_arithmetic() -> None:
    assert run_tool("calculator", {"expression": "2*(3+4)"})["value"] == 14
    assert run_tool("calculator", {"expression": "1/2"})["value"] == 0.5


def test_calculator_rejects_non_arithmetic() -> None:
    with pytest.raises(SchemaViolation):
        run_tool("calculator", {"expression": "__import__('os').system('ls')"})
    with pytest.raises(SchemaViolation):
        run_tool("calculator", {"expression": "1/0"})


def test_unknown_tool() -> None:
    with pytest.raises(SchemaViolation):
        run_tool("shell", {"command": "ls"})


def test_word_stats_and_clock() -> None:
    stats = run_tool("word_stats", {"text": "two words"})
    assert stats["words"] == 2
    assert stats["characters"] == 9
    clock = run_tool("utc_now", {})
    assert str(clock["utc"]).endswith("Z")


def test_extract_json_from_fence() -> None:
    payload = extract_json_object('Sure\n```json\n{"label": "positive"}\n```')
    assert payload == {"label": "positive"}


def test_extract_json_rejects_arrays() -> None:
    with pytest.raises(ValueError, match="object"):
        extract_json_object("[1, 2, 3]")


def test_token_estimate() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
