from __future__ import annotations

import pytest

from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.codex.choices import CODEX_MODEL_CHOICES
from codex_sdk_cli.domains.codex.schemas import RunRequest
from codex_sdk_cli.domains.micro_events.schemas import MicroEventExtractRequest
from codex_sdk_cli.domains.timelines.schemas import TimelineComposeEnqueueRequest
from codex_sdk_cli.settings import CliSettings

NEW_CODEX_MODELS = ("gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna")


@pytest.mark.parametrize("model", NEW_CODEX_MODELS)
def test_new_codex_models_are_allowed_across_settings_and_request_dtos(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    monkeypatch.setenv("CODEX_CLI_MODEL", model)

    assert model in CODEX_MODEL_CHOICES
    assert CliSettings().model == model
    assert RunRequest.model_validate({"prompt": "hello", "model": model}).model == model
    assert MicroEventExtractRequest.model_validate({"model": model}).model == model
    assert TimelineComposeEnqueueRequest.model_validate({"model": model}).model == model


def test_openapi_exposes_new_codex_models() -> None:
    schema = create_app().openapi()
    enum = schema["components"]["schemas"]["RunRequest"]["properties"]["model"][
        "anyOf"
    ][0]["enum"]

    assert set(NEW_CODEX_MODELS).issubset(enum)
