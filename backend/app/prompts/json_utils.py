import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", flags=re.DOTALL | re.IGNORECASE)


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = _FENCE.search(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("response did not contain a JSON object")
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("response contained invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON value must be an object")
    return payload
