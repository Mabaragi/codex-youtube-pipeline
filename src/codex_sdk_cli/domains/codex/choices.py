from __future__ import annotations

from typing import Literal

ApprovalChoice = Literal["auto-review", "deny-all"]
SandboxChoice = Literal["read-only", "workspace-write", "full-access"]
CodexModelChoice = Literal[
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-5.6-luna",
]
ReasoningEffortChoice = Literal["low", "medium", "high", "xhigh"]

DEFAULT_CODEX_MODEL: CodexModelChoice = "gpt-5.5"
DEFAULT_CODEX_REASONING_EFFORT: ReasoningEffortChoice = "medium"
DEFAULT_MICRO_EVENT_MODEL: CodexModelChoice = "gpt-5.6-sol"
DEFAULT_MICRO_EVENT_REASONING_EFFORT: ReasoningEffortChoice = "high"
DEFAULT_TIMELINE_MODEL: CodexModelChoice = "gpt-5.6-luna"
DEFAULT_TIMELINE_REASONING_EFFORT: ReasoningEffortChoice = "xhigh"
CODEX_MODEL_CHOICES: tuple[CodexModelChoice, ...] = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-5.6-luna",
)
CODEX_REASONING_EFFORT_CHOICES: tuple[ReasoningEffortChoice, ...] = (
    "low",
    "medium",
    "high",
    "xhigh",
)
