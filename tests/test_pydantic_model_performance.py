from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from timeit import repeat

import pytest
from openai_codex import ApprovalMode, Sandbox
from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True, slots=True)
class DataclassRunRequest:
    prompt: str
    thread_id: str | None
    cwd: Path | None
    model: str | None
    sandbox: Sandbox
    approval_mode: ApprovalMode
    persist: bool
    empty_base_instructions: bool
    empty_developer_instructions: bool


@dataclass(frozen=True, slots=True)
class DataclassRunOutput:
    thread_id: str
    turn_id: str
    status: str
    final_response: str
    usage: object | None


@dataclass(frozen=True, slots=True)
class DataclassLoginOutput:
    success: bool
    error: str | None = None


class PydanticRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt: str
    thread_id: str | None
    cwd: Path | None
    model: str | None
    sandbox: Sandbox
    approval_mode: ApprovalMode
    persist: bool
    empty_base_instructions: bool
    empty_developer_instructions: bool


class PydanticRunOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread_id: str
    turn_id: str
    status: str
    final_response: str
    usage: object | None


class PydanticLoginOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool
    error: str | None = None


ITERATIONS = 100_000
REPEATS = 7


@pytest.mark.performance
def test_pydantic_models_match_dataclass_shapes() -> None:
    cwd = Path("C:/repo")

    dataclass_request = DataclassRunRequest(
        prompt="hello",
        thread_id=None,
        cwd=cwd,
        model="gpt-test",
        sandbox=Sandbox.read_only,
        approval_mode=ApprovalMode.deny_all,
        persist=False,
        empty_base_instructions=False,
        empty_developer_instructions=False,
    )
    pydantic_request = PydanticRunRequest(
        prompt="hello",
        thread_id=None,
        cwd=cwd,
        model="gpt-test",
        sandbox=Sandbox.read_only,
        approval_mode=ApprovalMode.deny_all,
        persist=False,
        empty_base_instructions=False,
        empty_developer_instructions=False,
    )

    assert pydantic_request.prompt == dataclass_request.prompt
    assert pydantic_request.cwd == dataclass_request.cwd
    assert pydantic_request.sandbox is dataclass_request.sandbox
    assert pydantic_request.approval_mode is dataclass_request.approval_mode
    assert pydantic_request.persist is dataclass_request.persist
    assert pydantic_request.empty_base_instructions is dataclass_request.empty_base_instructions
    assert (
        pydantic_request.empty_developer_instructions
        is dataclass_request.empty_developer_instructions
    )

    dataclass_output = DataclassRunOutput("thread-1", "turn-1", "completed", "done", None)
    pydantic_output = PydanticRunOutput(
        thread_id="thread-1",
        turn_id="turn-1",
        status="completed",
        final_response="done",
        usage=None,
    )
    assert pydantic_output.model_dump() == asdict(dataclass_output)

    dataclass_login = DataclassLoginOutput(success=True, error=None)
    pydantic_login = PydanticLoginOutput(success=True, error=None)
    assert pydantic_login.model_dump() == asdict(dataclass_login)


@pytest.mark.performance
def test_pydantic_model_performance() -> None:
    cwd = Path("C:/repo")
    dataclass_request = DataclassRunRequest(
        "hello",
        None,
        cwd,
        "gpt-test",
        Sandbox.read_only,
        ApprovalMode.deny_all,
        False,
        False,
        False,
    )
    pydantic_request = PydanticRunRequest(
        prompt="hello",
        thread_id=None,
        cwd=cwd,
        model="gpt-test",
        sandbox=Sandbox.read_only,
        approval_mode=ApprovalMode.deny_all,
        persist=False,
        empty_base_instructions=False,
        empty_developer_instructions=False,
    )

    benchmarks = [
        _benchmark_pair(
            "RunRequest construct",
            lambda: DataclassRunRequest(
                "hello",
                None,
                cwd,
                "gpt-test",
                Sandbox.read_only,
                ApprovalMode.deny_all,
                False,
                False,
                False,
            ),
            lambda: PydanticRunRequest(
                prompt="hello",
                thread_id=None,
                cwd=cwd,
                model="gpt-test",
                sandbox=Sandbox.read_only,
                approval_mode=ApprovalMode.deny_all,
                persist=False,
                empty_base_instructions=False,
                empty_developer_instructions=False,
            ),
        ),
        _benchmark_pair(
            "RunOutput construct",
            lambda: DataclassRunOutput("thread-1", "turn-1", "completed", "done", None),
            lambda: PydanticRunOutput(
                thread_id="thread-1",
                turn_id="turn-1",
                status="completed",
                final_response="done",
                usage=None,
            ),
        ),
        _benchmark_pair(
            "LoginOutput construct",
            lambda: DataclassLoginOutput(True, None),
            lambda: PydanticLoginOutput(success=True, error=None),
        ),
        _benchmark_pair(
            "RunRequest attribute reads",
            lambda: (
                dataclass_request.prompt,
                dataclass_request.cwd,
                dataclass_request.sandbox,
            ),
            lambda: (
                pydantic_request.prompt,
                pydantic_request.cwd,
                pydantic_request.sandbox,
            ),
        ),
    ]
    dump_benchmark = _benchmark_statement(
        "RunRequest pydantic model_dump",
        lambda: pydantic_request.model_dump(mode="json"),
    )

    _print_table(benchmarks, dump_benchmark)

    for result in benchmarks:
        assert result.dataclass_us_per_call > 0
        assert result.pydantic_us_per_call > 0
        assert result.ratio > 0
    assert dump_benchmark.us_per_call > 0


@dataclass(frozen=True, slots=True)
class BenchmarkPair:
    name: str
    dataclass_us_per_call: float
    pydantic_us_per_call: float

    @property
    def ratio(self) -> float:
        return self.pydantic_us_per_call / self.dataclass_us_per_call


@dataclass(frozen=True, slots=True)
class BenchmarkSingle:
    name: str
    us_per_call: float


def _benchmark_pair(
    name: str,
    dataclass_operation: Callable[[], object],
    pydantic_operation: Callable[[], object],
) -> BenchmarkPair:
    return BenchmarkPair(
        name=name,
        dataclass_us_per_call=_median_us(dataclass_operation),
        pydantic_us_per_call=_median_us(pydantic_operation),
    )


def _benchmark_statement(name: str, operation: Callable[[], object]) -> BenchmarkSingle:
    return BenchmarkSingle(name=name, us_per_call=_median_us(operation))


def _median_us(operation: Callable[[], object]) -> float:
    timings = repeat(operation, number=ITERATIONS, repeat=REPEATS)
    return median(timings) / ITERATIONS * 1_000_000


def _print_table(benchmarks: list[BenchmarkPair], dump_benchmark: BenchmarkSingle) -> None:
    print()
    print(f"iterations_per_repeat={ITERATIONS}, repeats={REPEATS}")
    print("| case | dataclass us/call | pydantic us/call | pydantic/dataclass |")
    print("| --- | ---: | ---: | ---: |")
    for result in benchmarks:
        print(
            f"| {result.name} | {result.dataclass_us_per_call:.3f} | "
            f"{result.pydantic_us_per_call:.3f} | {result.ratio:.2f}x |"
        )
    print()
    print("| case | pydantic us/call |")
    print("| --- | ---: |")
    print(f"| {dump_benchmark.name} | {dump_benchmark.us_per_call:.3f} |")
