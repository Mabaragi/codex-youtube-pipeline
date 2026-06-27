from __future__ import annotations

from typing import Literal

ApprovalChoice = Literal["auto-review", "deny-all"]
SandboxChoice = Literal["read-only", "workspace-write", "full-access"]
CodexModelChoice = Literal["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"]
ReasoningEffortChoice = Literal["low", "medium", "high", "xhigh"]

DEFAULT_CODEX_MODEL: CodexModelChoice = "gpt-5.5"
DEFAULT_CODEX_REASONING_EFFORT: ReasoningEffortChoice = "medium"
CODEX_MODEL_CHOICES: tuple[CodexModelChoice, ...] = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
)
CODEX_REASONING_EFFORT_CHOICES: tuple[ReasoningEffortChoice, ...] = (
    "low",
    "medium",
    "high",
    "xhigh",
)
