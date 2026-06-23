from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from .ports import JsonObject


@runtime_checkable
class _JsonDumpable(Protocol):
    def model_dump(self, *, mode: str = "python", by_alias: bool = False) -> object:
        """Return a JSON-compatible object."""


def usage_to_json(value: object | None) -> JsonObject | None:
    if value is None:
        return None
    normalized = _to_jsonable(value)
    if isinstance(normalized, dict):
        return normalized
    return {"value": normalized}


def extract_usage_tokens(
    usage_json: JsonObject | None,
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    if usage_json is None:
        return None, None, None, None, None
    token_source = _token_source(usage_json)
    input_tokens = _int_at(
        token_source,
        "inputTokens",
        "input_tokens",
        "promptTokens",
        "prompt_tokens",
    )
    output_tokens = _int_at(
        token_source,
        "outputTokens",
        "output_tokens",
        "completionTokens",
        "completion_tokens",
    )
    total_tokens = _int_at(
        token_source,
        "totalTokens",
        "total_tokens",
        "total",
        "tokens",
    )
    cached_input_tokens = _int_at(
        token_source,
        "cachedInputTokens",
        "cached_input_tokens",
        "cachedTokens",
        "cached_tokens",
        ("inputTokensDetails", "cachedTokens"),
        ("inputTokensDetails", "cached_tokens"),
        ("input_tokens_details", "cached_tokens"),
        ("prompt_tokens_details", "cached_tokens"),
    )
    reasoning_output_tokens = _int_at(
        token_source,
        "reasoningOutputTokens",
        "reasoning_output_tokens",
        "reasoningTokens",
        "reasoning_tokens",
        ("outputTokensDetails", "reasoningTokens"),
        ("outputTokensDetails", "reasoning_tokens"),
        ("output_tokens_details", "reasoning_tokens"),
        ("completion_tokens_details", "reasoning_tokens"),
    )
    return (
        input_tokens,
        output_tokens,
        total_tokens,
        cached_input_tokens,
        reasoning_output_tokens,
    )


def _token_source(usage_json: JsonObject) -> JsonObject:
    for key in ("total", "last"):
        value = usage_json.get(key)
        if isinstance(value, dict):
            return {str(item_key): item_value for item_key, item_value in value.items()}
    return usage_json


def _to_jsonable(value: object) -> object:
    if isinstance(value, _JsonDumpable):
        return _to_jsonable(value.model_dump(mode="json", by_alias=True))
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _int_at(data: JsonObject, *paths: str | tuple[str, ...]) -> int | None:
    for path in paths:
        value = _value_at(data, (path,) if isinstance(path, str) else path)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
    return None


def _value_at(data: JsonObject, path: tuple[str, ...]) -> object | None:
    current: object = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
