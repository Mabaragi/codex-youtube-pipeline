from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox
from openai_codex.generated.v2_all import ReasoningEffort
from openai_codex.models import JsonObject as SdkJsonObject
from pydantic import BaseModel, ConfigDict

from codex_sdk_cli.domains.codex.choices import (
    CODEX_MODEL_CHOICES,
    CODEX_REASONING_EFFORT_CHOICES,
)
from codex_sdk_cli.domains.micro_events.output_validation import (
    _ExtractorOutput,
    _parse_extractor_output,
    _validate_extractor_output,
    micro_event_output_schema,
)
from codex_sdk_cli.settings import CliSettings


class SmallOutput(BaseModel):
    start_cue_id: str
    status: Literal["OK"]
    values: list[int]

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class VerificationCase:
    name: str
    prompt: str
    output_schema: dict[str, object] | None
    validate: Callable[[str], None]
    required_to_pass: bool


def main() -> None:
    args = _parse_args()
    results = asyncio.run(
        _run_verification(
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            timeout_seconds=args.timeout_seconds,
        )
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    failed = [
        str(result["case"])
        for result in results
        if result["requiredToPass"] and not result.get("validated", False)
    ]
    if failed:
        raise SystemExit(f"Structured output verification failed: {', '.join(failed)}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify Codex output_schema behavior with ephemeral synthetic turns."
    )
    parser.add_argument("--model", choices=CODEX_MODEL_CHOICES, default="gpt-5.6-luna")
    parser.add_argument(
        "--reasoning-effort",
        choices=CODEX_REASONING_EFFORT_CHOICES,
        default="xhigh",
    )
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser.parse_args()


async def _run_verification(
    *,
    model: str,
    reasoning_effort: str,
    timeout_seconds: int,
) -> list[dict[str, object]]:
    settings = CliSettings()
    config = CodexConfig(
        codex_bin=str(settings.codex_bin) if settings.codex_bin else None,
        config_overrides=(f'model_reasoning_effort="{reasoning_effort}"',),
    )
    effort = ReasoningEffort(reasoning_effort)
    async with AsyncCodex(config=config) as codex:
        results: list[dict[str, object]] = []
        for case in _verification_cases():
            results.append(
                await _run_case(
                    codex,
                    case,
                    model=model,
                    effort=effort,
                    timeout_seconds=timeout_seconds,
                )
            )
        return results


def _verification_cases() -> tuple[VerificationCase, ...]:
    small_prompt = (
        "Return JSON only. Use the camelCase key startCueId, add an extra key note, "
        "set status to OK, and values to [1, 2]. Do not use snake_case."
    )
    micro_prompt = (
        "Return JSON only for this single cue. Prefer camelCase keys such as startCueId "
        "and evidenceCueIds if possible, and include confidence=0.9.\n"
        "Cue: [tr1-c000001] The streamer explains today's game goal.\n"
        "Create exactly one event and no excluded ranges or ASR corrections."
    )
    return (
        VerificationCase(
            name="prompt_only_baseline",
            prompt=small_prompt,
            output_schema=None,
            validate=_validate_small_output,
            required_to_pass=False,
        ),
        VerificationCase(
            name="small_pydantic_schema",
            prompt=small_prompt,
            output_schema=cast(dict[str, object], SmallOutput.model_json_schema()),
            validate=_validate_small_output,
            required_to_pass=True,
        ),
        VerificationCase(
            name="raw_micro_event_pydantic_schema",
            prompt=micro_prompt,
            output_schema=cast(dict[str, object], _ExtractorOutput.model_json_schema()),
            validate=_validate_micro_event_output,
            required_to_pass=False,
        ),
        VerificationCase(
            name="strict_micro_event_schema",
            prompt=micro_prompt,
            output_schema=micro_event_output_schema(),
            validate=_validate_micro_event_output,
            required_to_pass=True,
        ),
    )


async def _run_case(
    codex: AsyncCodex,
    case: VerificationCase,
    *,
    model: str,
    effort: ReasoningEffort,
    timeout_seconds: int,
) -> dict[str, object]:
    report: dict[str, object] = {
        "case": case.name,
        "schemaSupplied": case.output_schema is not None,
        "requiredToPass": case.required_to_pass,
    }
    try:
        thread = await codex.thread_start(
            approval_mode=ApprovalMode.deny_all,
            base_instructions=" ",
            developer_instructions=" ",
            ephemeral=True,
            model=model,
            sandbox=Sandbox.read_only,
        )
        async with asyncio.timeout(timeout_seconds):
            turn = await thread.run(
                case.prompt,
                effort=effort,
                output_schema=cast(SdkJsonObject | None, case.output_schema),
            )
        response = turn.final_response or ""
        report["status"] = str(getattr(turn.status, "value", turn.status))
        report["response"] = response
        try:
            case.validate(response)
        except Exception as exc:
            report["validated"] = False
            report["validationError"] = f"{type(exc).__name__}: {exc}"
        else:
            report["validated"] = True
    except Exception as exc:
        report["validated"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


def _validate_small_output(response: str) -> None:
    SmallOutput.model_validate_json(response)


def _validate_micro_event_output(response: str) -> None:
    _validate_extractor_output(_parse_extractor_output(response))


if __name__ == "__main__":
    main()
