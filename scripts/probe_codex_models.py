from __future__ import annotations

import asyncio
import json

from openai_codex.generated.v2_all import ReasoningEffort

from codex_sdk_cli.runner import (
    RunRequest,
    open_codex,
    parse_approval,
    parse_sandbox,
    run_prompt,
)
from codex_sdk_cli.settings import CliSettings

PROBE_MODELS = (
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-5.6-luna",
)


async def probe_models() -> list[dict[str, object]]:
    settings = CliSettings()
    results: list[dict[str, object]] = []
    async with open_codex(settings.codex_config()) as codex:
        for model in PROBE_MODELS:
            try:
                output = await run_prompt(
                    codex,
                    RunRequest(
                        prompt="Reply with OK.",
                        thread_id=None,
                        cwd=None,
                        model=model,
                        reasoning_effort=ReasoningEffort.medium,
                        sandbox=parse_sandbox("read-only"),
                        approval_mode=parse_approval("deny-all"),
                        persist=False,
                        base_instructions=None,
                        developer_instructions=None,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - probe must report each model independently
                results.append(
                    {
                        "model": model,
                        "available": False,
                        "errorType": type(exc).__name__,
                        "error": str(exc) or type(exc).__name__,
                    }
                )
                continue

            results.append(
                {
                    "model": model,
                    "available": True,
                    "status": output.status,
                    "threadId": output.thread_id,
                    "turnId": output.turn_id,
                }
            )
    return results


def main() -> None:
    print(json.dumps(asyncio.run(probe_models()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
