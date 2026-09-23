# 단발성 영상 타임라인

`codex-demo timeline once`는 채널 등록과 자동 수집 작업 없이 YouTube 영상 ID 하나를 처리한다. 운영 데이터베이스에서는 현재 활성 프롬프트를 읽기 전용으로 조회한다. 자막, 생성 결과, 체크포인트는 기본적으로 Git에서 제외된 `.home-deploy/one-shot/` 아래에 저장하며 DB·MinIO·게시 경로에 쓰지 않는다.

## 실행

```powershell
uv run codex-demo timeline once plan --video-id f3KJMN0jPfg
uv run codex-demo timeline once run --plan "<planPath>" --confirm-plan-hash "<planHash>"
uv run codex-demo timeline once status --run-dir "<runDir>"
uv run codex-demo timeline once verify --run-dir "<runDir>"
```

`plan`의 JSON 결과에 `planPath`, `runDir`, `planHash`, 자막 소스, 예상 마이크로 이벤트 창 수와 활성 프롬프트 버전이 포함된다. `run`은 계획 뒤 활성 프롬프트가 바뀌었으면 `PROMPT_CHANGED`로 거부한다. 실패하거나 중단된 실행은 `resume --run-dir "<runDir>"`로 이어간다. 이때 계획에 고정된 프롬프트를 그대로 사용하고 완료된 ASR 청크와 마이크로 이벤트 창을 재사용한다. 계획만 만든 상태에서는 `run`을 사용한다.

기본 언어 우선순위는 한국어, 영어다. 자막이 없다는 확정 응답에만 로컬 ASR로 전환하며 조회 오류는 오류로 보고한다. 자막을 쓰지 않으려면 `plan --transcript-mode asr`을 지정한다. ASR 기본값은 `turbo/ko/cuda`이고 CPU 실행은 `plan --asr-device cpu`로 선택한다. 마이크로 이벤트 창은 기본 30분, 문맥 겹침은 5분이다. `plan --help`에서 모델·추론 강도·창 크기·ASR 옵션을 확인할 수 있다.

## 로컬 파일과 검증

한 실행은 `<output-root>/<video-id>/<plan-hash-prefix>/`에 저장된다. `timeline.json`은 영상 정보, 정규화된 타임라인, 참조되는 마이크로 이벤트, 검증 경고를 담는다. `plan.json`에는 입력·모델 설정·프롬프트 본문과 해시가 포함된다. `inputs/`에는 자막 또는 ASR 원문과 cue가, `checkpoints/`에는 완료된 청크와 창이, `usage.jsonl`과 `traces/`에는 사용량과 생성 기록이 들어간다. 이 파일에는 비공개 원문과 프롬프트가 있으므로 외부에 공유하거나 Git에 추가하지 않는다.

`verify`는 성공한 실행의 파일 해시, 영상 ID, 타임라인의 마이크로 이벤트 참조를 검사한다. 동일한 계획으로 완료된 `run`을 다시 호출하면 기존 검증 결과를 반환한다. JSON 출력의 `ok`, `operation`, `result` 또는 `error.code`를 사용해 자동화할 수 있다. `version`, `capabilities`, `schema <command>`로 명령 인터페이스를 조회할 수 있다.

실제 영상 처리에는 YouTube Data API 키, 읽기 가능한 활성 프롬프트 DB, Codex 런타임이 필요하다. 자막이 없는 영상의 ASR에는 `yt-dlp`, `ffmpeg`, `ffprobe`, Faster Whisper와 선택한 장치가 추가로 필요하다. `f3KJMN0jPfg`의 실제 생성과 결과 평가는 별도 실행 단계에서 수행한다.
