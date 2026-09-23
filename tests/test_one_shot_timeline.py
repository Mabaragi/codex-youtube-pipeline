from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from click.testing import CliRunner

from codex_sdk_cli.application.one_shot.ports import RunOptions, VideoMetadata
from codex_sdk_cli.application.one_shot.service import OneShotError, OneShotTimelineService
from codex_sdk_cli.domains.asr.ports import (
    AudioTranscriptionRequest,
    AudioTranscriptionResult,
    AudioTranscriptionSegment,
)
from codex_sdk_cli.domains.asr.use_cases import (
    FasterWhisperTranscribeRequest,
    TranscribeYouTubeAudioUseCase,
)
from codex_sdk_cli.domains.codex.ports import CodexRunCommand, CodexRunResult
from codex_sdk_cli.domains.prompts.constants import PromptKey
from codex_sdk_cli.domains.prompts.ports import ResolvedPrompt
from codex_sdk_cli.domains.youtube_transcripts.exceptions import (
    YouTubeTranscriptNotFound,
    YouTubeTranscriptUpstreamError,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptFetchResult,
    YouTubeTranscriptSegment,
)
from codex_sdk_cli.infra.local_generation import prompts as prompt_module
from codex_sdk_cli.infra.local_generation import youtube as youtube_module
from codex_sdk_cli.infra.local_generation.files import (
    FileAsrCheckpoints,
    FileCueRepository,
    FileTranscriptRepository,
    FileTranscriptStorage,
)
from codex_sdk_cli.infra.local_generation.generation import LocalGenerationRunner
from codex_sdk_cli.infra.local_generation.store import LocalRunStore
from codex_sdk_cli.once_cli import once
from codex_sdk_cli.settings import CliSettings

VIDEO_ID = "abcdefghijk"


class FakeVideos:
    def __init__(self, duration_seconds: int = 60) -> None:
        self.calls = 0
        self.duration_seconds = duration_seconds

    async def lookup(self, youtube_video_id: str) -> VideoMetadata:
        self.calls += 1
        assert youtube_video_id == VIDEO_ID
        return VideoMetadata(
            youtube_video_id=VIDEO_ID,
            title="Local test video",
            description="Test description",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            duration=f"PT{self.duration_seconds // 60}M",
            duration_seconds=self.duration_seconds,
            thumbnail_url=None,
            channel_id="channel-test",
            channel_name="Test channel",
            is_embeddable=True,
        )


class FakeCaptions:
    def __init__(self, *, absent: bool = False, broken: bool = False, long: bool = False) -> None:
        self.absent = absent
        self.broken = broken
        self.long = long

    async def fetch(
        self, youtube_video_id: str, languages: tuple[str, ...]
    ) -> YouTubeTranscriptFetchResult:
        assert youtube_video_id == VIDEO_ID
        assert languages[0] == "ko"
        if self.broken:
            raise YouTubeTranscriptUpstreamError("Temporary provider failure")
        if self.absent:
            raise YouTubeTranscriptNotFound("No captions")
        return YouTubeTranscriptFetchResult(
            video_id=VIDEO_ID,
            language="Korean",
            language_code="ko",
            is_generated=True,
            segments=tuple(
                YouTubeTranscriptSegment(f"topic {index}", index * 30, 30)
                for index in range(4 if self.long else 2)
            ),
        )


class FakePrompts:
    def __init__(self) -> None:
        self.version = 10
        self.calls = 0

    async def resolve(self) -> dict[PromptKey, ResolvedPrompt]:
        self.calls += 1
        return {
            key: ResolvedPrompt(
                key=key,
                version_id=self.version,
                version_label=f"active-{self.version}",
                body=f"Generate structured {key} output version {self.version}.",
                body_sha256=f"{self.version:064x}",
                source="database",
            )
            for key in (
                "micro_event_extract",
                "timeline_compose",
                "timeline_episode_repair",
            )
        }


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.windows: list[int] = []

    async def run_prompt(self, command: CodexRunCommand) -> CodexRunResult:
        context = command.usage_context
        assert context is not None
        self.calls.append(context.operation)
        if context.operation == "extract_window":
            window = context.window_index or 1
            self.windows.append(window)
            first = (window - 1) * 2 + 1
            start_cue = f"tr1-c{first:06d}"
            end_cue = f"tr1-c{first + 1:06d}"
            payload: dict[str, Any] = {
                "events": [
                    {
                        "start_cue_id": start_cue,
                        "end_cue_id": end_cue,
                        "event": "The speaker explains a topic.",
                        "program_mode": "JUST_CHATTING",
                        "content_kind": "META_CHAT",
                        "topics": ["test topic"],
                        "relation_to_previous": "NEW_TOPIC",
                        "continues_to_next": False,
                        "evidence_cue_ids": [start_cue, end_cue],
                        "support_level": "DIRECT",
                    }
                ],
                "excluded_ranges": [],
                "asr_correction_candidates": [],
            }
        elif context.operation == "compose_video":
            payload = {
                "video_summary": {
                    "title": "Test timeline",
                    "summary": "The topic is discussed.",
                    "display_title": "Test timeline",
                    "display_summary": "The topic is discussed.",
                    "main_topics": ["test topic"],
                },
                "blocks": [
                    {
                        "block_id": "block_001",
                        "block_type": "JUST_CHATTING",
                        "title": "Test block",
                        "summary": "The topic is discussed.",
                        "display_title": "Test block",
                        "display_summary": "The topic is discussed.",
                        "episode_ids": ["episode_001"],
                    }
                ],
                "episodes": [
                    {
                        "episode_id": "episode_001",
                        "parent_block_id": "block_001",
                        "start_micro_event_id": "me_0001",
                        "end_micro_event_id": "me_0001",
                        "program_mode": "JUST_CHATTING",
                        "primary_content_kind": "META_CHAT",
                        "title": "Test episode",
                        "summary": "The topic is discussed.",
                        "display_title": "Test episode",
                        "display_summary": "The topic is discussed.",
                        "topics": ["test topic"],
                        "viewer_tags": ["META"],
                        "highlight_micro_event_ids": ["me_0001"],
                        "visibility": "DEFAULT",
                    }
                ],
                "topic_clusters": [],
                "review_flags": [],
            }
        else:
            raise AssertionError(context.operation)
        return CodexRunResult(
            thread_id="fake-thread",
            turn_id="fake-turn",
            status="completed",
            final_response=json.dumps(payload),
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


class FailSecondWindowRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.fail_once = True

    async def run_prompt(self, command: CodexRunCommand) -> CodexRunResult:
        context = command.usage_context
        assert context is not None
        if context.operation == "extract_window" and context.window_index == 2 and self.fail_once:
            self.calls.append(context.operation)
            self.windows.append(2)
            raise RuntimeError("Simulated interruption")
        return await super().run_prompt(command)


class NoAsr:
    calls = 0

    async def transcribe(self, **_kwargs: object) -> None:
        self.calls += 1
        raise AssertionError("ASR should not be called")


class FakeDownloader:
    async def download_audio(self, *, video_id: str, output_dir: Path) -> Path:
        path = output_dir / f"{video_id}.webm"
        path.write_bytes(b"audio")
        return path


class FakeChunker:
    def __init__(self, duration_seconds: float = 60) -> None:
        self.duration_seconds = duration_seconds

    async def probe_duration_seconds(self, audio_path: Path) -> float:
        del audio_path
        return self.duration_seconds

    async def create_chunk(
        self,
        *,
        audio_path: Path,
        output_path: Path,
        start_seconds: float,
        duration_seconds: float,
    ) -> Path:
        del audio_path, start_seconds, duration_seconds
        output_path.write_bytes(b"chunk")
        return output_path


class FakeTranscriber:
    def __init__(self) -> None:
        self.calls = 0
        self.fail_second = False

    async def transcribe(self, request: AudioTranscriptionRequest) -> AudioTranscriptionResult:
        self.calls += 1
        assert request.device == "cuda"
        if self.calls == 2 and self.fail_second:
            raise RuntimeError("Simulated ASR interruption")
        return AudioTranscriptionResult(
            segments=(
                AudioTranscriptionSegment("first topic", 0, 30),
                AudioTranscriptionSegment("second topic", 30, 60),
            ),
            device="cuda",
            compute_type="float16",
        )


class FakeLocalAsr:
    def __init__(self, duration_seconds: float = 60) -> None:
        self.transcriber = FakeTranscriber()
        self.calls = 0
        self.duration_seconds = duration_seconds

    async def transcribe(
        self, *, youtube_video_id: str, run_dir: Path, options: RunOptions
    ) -> object:
        self.calls += 1
        use_case = TranscribeYouTubeAudioUseCase(
            downloader=FakeDownloader(),
            chunker=FakeChunker(self.duration_seconds),
            transcriber=self.transcriber,
            storage=FileTranscriptStorage(run_dir),
            transcripts=cast(Any, FileTranscriptRepository(run_dir)),
            cues=cast(Any, FileCueRepository(run_dir)),
            checkpoints=FileAsrCheckpoints(run_dir),
        )
        return (
            await use_case.execute(
                FasterWhisperTranscribeRequest(
                    video=youtube_video_id,
                    model_size=options.asr_model,
                    language=options.asr_language,
                    device=options.asr_device,
                    compute_type=options.asr_compute_type,
                    chunk_minutes=options.asr_chunk_minutes,
                    overlap_seconds=options.asr_overlap_seconds,
                    beam_size=options.asr_beam_size,
                    vad_filter=options.asr_vad_filter,
                )
            )
        ).transcript


def _service(
    *,
    captions: FakeCaptions,
    prompts: FakePrompts,
    asr: object,
    runtime: FakeRuntime,
    video_duration_seconds: int = 60,
) -> OneShotTimelineService:
    return OneShotTimelineService(
        videos=FakeVideos(video_duration_seconds),
        captions=captions,
        prompts=prompts,
        asr=asr,  # type: ignore[arg-type]
        generation=LocalGenerationRunner(CliSettings(), runtime=cast(Any, runtime)),
        store=LocalRunStore(),
    )


def test_caption_run_is_local_verified_and_idempotent(tmp_path: Path) -> None:
    async def scenario() -> None:
        prompts = FakePrompts()
        runtime = FakeRuntime()
        asr = NoAsr()
        service = _service(captions=FakeCaptions(), prompts=prompts, asr=asr, runtime=runtime)
        plan = await service.plan(video_id=VIDEO_ID, output_root=tmp_path, options=RunOptions())
        run_dir = Path(str(plan["runDir"]))
        assert plan["transcriptSource"] == "youtube"
        assert (run_dir / "inputs" / "cues.json").exists()
        result = await service.run(
            plan_path=Path(str(plan["planPath"])), confirm_plan_hash=str(plan["planHash"])
        )
        assert result["status"] == "succeeded"
        assert result["episodeCount"] == 1
        assert asr.calls == 0
        assert runtime.calls == ["extract_window", "compose_video"]
        timeline = json.loads((run_dir / "timeline.json").read_text(encoding="utf-8"))
        assert (
            timeline["timeline"]["episodes"][0]["startMicroEventCandidateId"]
            == timeline["microEvents"][0]["sourceCandidateId"]
        )
        assert timeline["microEvents"][0]["id"] == "me_0001"
        prompts.version = 11
        again = await service.run(
            plan_path=Path(str(plan["planPath"])), confirm_plan_hash=str(plan["planHash"])
        )
        assert again == result
        assert runtime.calls == ["extract_window", "compose_video"]
        assert prompts.calls == 2
        assert service.status(run_dir=run_dir)["status"] == "succeeded"
        (run_dir / "inputs" / "cues.json").write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="artifact"):
            service.verify(run_dir=run_dir)

    asyncio.run(scenario())


def test_cli_reports_json_error_codes_and_discovery(tmp_path: Path) -> None:
    service = _service(
        captions=FakeCaptions(), prompts=FakePrompts(), asr=NoAsr(), runtime=FakeRuntime()
    )
    runner = CliRunner()
    plan_result = runner.invoke(
        once,
        ["plan", "--video-id", VIDEO_ID, "--output-root", str(tmp_path)],
        obj={"once_service": service},
    )
    assert plan_result.exit_code == 0
    plan = json.loads(plan_result.stdout)["result"]
    rejected = runner.invoke(
        once,
        ["run", "--plan", plan["planPath"], "--confirm-plan-hash", "wrong"],
        obj={"once_service": service},
    )
    assert rejected.exit_code == 4
    assert json.loads(rejected.stderr)["error"]["code"] == "PLAN_HASH_MISMATCH"
    invalid = runner.invoke(once, ["run", "--plan", plan["planPath"]])
    assert invalid.exit_code == 2
    assert json.loads(invalid.stderr)["error"]["code"] == "INVALID_ARGUMENT"
    capabilities = runner.invoke(once, ["capabilities"])
    assert json.loads(capabilities.stdout)["result"]["publication"] is False


def test_active_prompt_source_uses_read_only_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeBind:
        dialect = type("Dialect", (), {"name": "postgresql"})()

    class FakeSession:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def get_bind(self) -> FakeBind:
            return FakeBind()

        async def execute(self, statement: object) -> None:
            self.statements.append(str(statement))

    class FakeEngine:
        def __init__(self) -> None:
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    class FakeResolver:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def resolve_prompt(self, key: PromptKey) -> ResolvedPrompt:
            return (await FakePrompts().resolve())[key]

    session = FakeSession()
    engine = FakeEngine()
    monkeypatch.setattr(prompt_module, "create_database_engine", lambda *_args, **_kwargs: engine)
    monkeypatch.setattr(prompt_module, "create_session_factory", lambda _engine: lambda: session)
    monkeypatch.setattr(prompt_module, "SqlAlchemyPromptRepository", lambda _session: object())
    monkeypatch.setattr(prompt_module, "PromptResolver", FakeResolver)
    result = asyncio.run(prompt_module.ReadOnlyActivePrompts(CliSettings()).resolve())
    assert "micro_event_extract" in result
    assert session.statements == ["SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"]
    assert engine.disposed is True


def test_direct_video_lookup_reads_public_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.params["id"] == VIDEO_ID
        assert request.url.params["part"] == "snippet,contentDetails,status"
        return httpx.Response(
            200,
            json={
                "kind": "youtube#videoListResponse",
                "etag": "test-etag",
                "pageInfo": {"totalResults": 1, "resultsPerPage": 1},
                "items": [
                    {
                        "id": VIDEO_ID,
                        "snippet": {
                            "title": "Test video",
                            "description": "Description",
                            "publishedAt": "2026-07-01T00:00:00Z",
                            "channelId": "channel-test",
                            "channelTitle": "Test channel",
                            "thumbnails": {"high": {"url": "https://example.test/thumb.jpg"}},
                        },
                        "contentDetails": {"duration": "PT4H24M19S"},
                        "status": {"embeddable": True, "privacyStatus": "public"},
                    }
                ],
            },
        )

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        youtube_module.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    lookup = youtube_module.YouTubeSingleVideoLookup(CliSettings(youtube_data_api_key="test-key"))
    video = asyncio.run(lookup.lookup(VIDEO_ID))
    assert video.duration_seconds == 4 * 3600 + 24 * 60 + 19
    assert video.thumbnail_url == "https://example.test/thumb.jpg"
    assert video.is_embeddable is True


def test_prompt_change_rejects_new_run_and_resume_keeps_snapshot(tmp_path: Path) -> None:
    async def scenario() -> None:
        prompts = FakePrompts()
        runtime = FailSecondWindowRuntime()
        service = _service(
            captions=FakeCaptions(long=True), prompts=prompts, asr=NoAsr(), runtime=runtime
        )
        options = RunOptions(window_minutes=1, overlap_minutes=0)
        plan = await service.plan(video_id=VIDEO_ID, output_root=tmp_path, options=options)
        run_dir = Path(str(plan["runDir"]))
        with pytest.raises(RuntimeError, match="Simulated interruption"):
            await service.run(
                plan_path=Path(str(plan["planPath"])), confirm_plan_hash=str(plan["planHash"])
            )
        assert service.status(run_dir=run_dir)["status"] == "failed"
        assert service.status(run_dir=run_dir)["completedMicroWindows"] == 1
        prompts.version = 11
        with pytest.raises(OneShotError, match="active prompt") as error:
            await service.run(
                plan_path=Path(str(plan["planPath"])), confirm_plan_hash=str(plan["planHash"])
            )
        assert error.value.code == "PROMPT_CHANGED"
        new_plan = await service.plan(video_id=VIDEO_ID, output_root=tmp_path, options=options)
        assert new_plan["planHash"] != plan["planHash"]
        prompt_versions = cast(dict[str, dict[str, object]], new_plan["prompts"])
        assert prompt_versions["micro_event_extract"]["versionId"] == 11
        runtime.fail_once = False
        await service.resume(run_dir=run_dir)
        assert service.verify(run_dir=run_dir)["status"] == "succeeded"
        assert runtime.windows.count(1) == 1
        assert runtime.windows[-1] == 2

    asyncio.run(scenario())


def test_asr_fallback_uses_file_checkpoints_and_upstream_error_does_not_fallback(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        asr = FakeLocalAsr()
        service = _service(
            captions=FakeCaptions(absent=True),
            prompts=FakePrompts(),
            asr=asr,
            runtime=FakeRuntime(),
        )
        plan = await service.plan(video_id=VIDEO_ID, output_root=tmp_path, options=RunOptions())
        assert plan["transcriptSource"] == "asr"
        await service.run(
            plan_path=Path(str(plan["planPath"])), confirm_plan_hash=str(plan["planHash"])
        )
        run_dir = Path(str(plan["runDir"]))
        assert asr.transcriber.calls == 1
        assert len(list((run_dir / "checkpoints" / "asr").glob("chunk-*.json"))) == 1
        assert (run_dir / "inputs" / "transcript.json").exists()
        broken = _service(
            captions=FakeCaptions(broken=True),
            prompts=FakePrompts(),
            asr=asr,
            runtime=FakeRuntime(),
        )
        with pytest.raises(YouTubeTranscriptUpstreamError):
            await broken.plan(
                video_id=VIDEO_ID, output_root=tmp_path / "broken", options=RunOptions()
            )
        assert asr.calls == 1

    asyncio.run(scenario())


def test_asr_resume_reuses_completed_chunk(tmp_path: Path) -> None:
    async def scenario() -> None:
        asr = FakeLocalAsr(duration_seconds=120)
        asr.transcriber.fail_second = True
        service = _service(
            captions=FakeCaptions(absent=True),
            prompts=FakePrompts(),
            asr=asr,
            runtime=FakeRuntime(),
            video_duration_seconds=120,
        )
        plan = await service.plan(
            video_id=VIDEO_ID,
            output_root=tmp_path,
            options=RunOptions(asr_chunk_minutes=1, window_minutes=1, overlap_minutes=0),
        )
        run_dir = Path(str(plan["runDir"]))
        assert plan["estimatedAsrChunks"] == 2
        with pytest.raises(RuntimeError, match="ASR interruption"):
            await service.run(
                plan_path=Path(str(plan["planPath"])), confirm_plan_hash=str(plan["planHash"])
            )
        assert service.status(run_dir=run_dir)["completedAsrChunks"] == 1
        asr.transcriber.fail_second = False
        await service.resume(run_dir=run_dir)
        assert asr.transcriber.calls == 3
        assert service.verify(run_dir=run_dir)["status"] == "succeeded"

    asyncio.run(scenario())
