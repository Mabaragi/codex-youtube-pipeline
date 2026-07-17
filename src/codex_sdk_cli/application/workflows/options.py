from __future__ import annotations

from datetime import UTC, datetime

from codex_sdk_cli.domains.work.models import WorkflowRun, WorkItem


def required_output_int(item: WorkItem, key: str) -> int:
    value = item.output_json.get(key) if item.output_json is not None else None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if key == "transcriptId" and item.output_transcript_id is not None:
        return item.output_transcript_id
    raise RuntimeError(f"Work item {item.id} has no integer {key} output.")


def required_output_str(item: WorkItem, key: str) -> str:
    value = item.output_json.get(key) if item.output_json is not None else None
    if isinstance(value, str) and value:
        return value
    raise RuntimeError(f"Work item {item.id} has no string {key} output.")


def option_str(workflow: WorkflowRun, key: str) -> str:
    value = workflow.options_json.get(key)
    if isinstance(value, str) and value:
        return value
    raise RuntimeError(f"Workflow option {key} must be a non-empty string.")


def option_str_list(workflow: WorkflowRun, key: str) -> list[str]:
    value = workflow.options_json.get(key)
    if isinstance(value, (list, tuple)) and value and all(
        isinstance(item, str) and item for item in value
    ):
        return list(value)
    raise RuntimeError(f"Workflow option {key} must be a non-empty string list.")


def option_bool(workflow: WorkflowRun, key: str) -> bool:
    value = workflow.options_json.get(key)
    if isinstance(value, bool):
        return value
    raise RuntimeError(f"Workflow option {key} must be a boolean.")


def option_int(workflow: WorkflowRun, key: str) -> int:
    value = workflow.options_json.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise RuntimeError(f"Workflow option {key} must be an integer.")


def option_int_default(workflow: WorkflowRun, key: str, default: int) -> int:
    value = workflow.options_json.get(key, default)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise RuntimeError(f"Workflow option {key} must be an integer.")


def option_optional_int(workflow: WorkflowRun, key: str) -> int | None:
    value = workflow.options_json.get(key)
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise RuntimeError(f"Workflow option {key} must be an integer or null.")


def option_bool_default(workflow: WorkflowRun, key: str, default: bool) -> bool:
    value = workflow.options_json.get(key, default)
    if isinstance(value, bool):
        return value
    raise RuntimeError(f"Workflow option {key} must be a boolean.")


def option_str_default(workflow: WorkflowRun, key: str, default: str) -> str:
    value = workflow.options_json.get(key, default)
    if isinstance(value, str) and value:
        return value
    raise RuntimeError(f"Workflow option {key} must be a non-empty string.")


def option_datetime(workflow: WorkflowRun, key: str) -> datetime:
    value = option_str(workflow, key)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return aware_datetime(parsed)


def aware_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def input_int(item: WorkItem, key: str) -> int | None:
    value = item.input_json.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def output_int(item: WorkItem, key: str) -> int | None:
    value = item.output_json.get(key) if item.output_json is not None else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None
