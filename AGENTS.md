# Agents Guide

## Project

이 저장소는 Python `codex-demo` CLI와 `codex-api` FastAPI 예제 프로젝트다. YouTube metadata/transcript 수집, cue 생성, micro-event 추출, timeline 구성, archive publish 흐름을 로컬에서 실험한다.

## Context Vault

반복 작업의 절차·검증·개선 기록은 [vaults/INDEX.md](vaults/INDEX.md)에서 작업에
필요한 문서만 골라 읽는다. 사람을 위한 공개 설명은 [docs/INDEX.md](docs/INDEX.md)를
따르며, private runbook과 worklog는 공개 저장소에 기록하지 않는다.

## Reading Order

1. 이 `AGENTS.md`.
2. [vaults/INDEX.md](vaults/INDEX.md)에서 작업별 guide를 고른다.
3. 공개 동작·구현 배경·운영 절차를 다루는 작업일 때만
   [docs/INDEX.md](docs/INDEX.md)에서 필요한 문서를 고른다.
4. 대상 코드와 관련 테스트를 읽는다.
5. Ops UI 작업은 [ops-ui/AGENTS.md](ops-ui/AGENTS.md)를 먼저 추가로 읽는다.

## Always Follow

- 여러 에이전트가 같은 작업 공간에서 동시에 작업할 수 있음을 전제로 한다.
- 자신의 요청 범위와 구현사항에 집중한다.
- 다른 에이전트나 사용자의 변경을 임의로 되돌리거나 정리하지 않는다.
- 관련 없는 파일, 설정, 기록은 건드리지 않는다.
- 충돌 가능성이 보이면 먼저 현재 상태를 확인하고, 필요한 경우 사용자에게 묻는다.
- 새 Python 코드는 domain-first 구조를 따른다.
- CLI command 함수와 FastAPI route handler는 얇게 유지한다.
- 환경 설정은 `src/codex_sdk_cli/settings.py`의 `CliSettings`와 `CODEX_CLI_` prefix를 통해 관리한다.
- DB schema 변경은 SQLAlchemy 모델과 Alembic migration으로만 수행한다.
- 앱 코드나 테스트에서 `metadata.create_all()`/`drop_all()`을 호출하지 않는다.
- 자동 테스트에서는 실제 Codex app-server, 로그인, YouTube, MinIO, 네트워크 호출을 띄우지 않는다. Protocol/fake 기반 테스트를 사용한다.
- `openai-codex`는 베타 SDK이며 prerelease runtime dependency가 필요하므로 `[tool.uv] prerelease = "allow"`를 유지한다.

## Public Repository Safety

- `.home-deploy/`, `data/`, DB, raw transcript/cue/event/timeline export, LLM trace, production prompt pack, API key, token, private runbook은 commit하지 않는다.
- `src/codex_sdk_cli/domains/prompts/resources/`의 prompt 파일은 public-safe sample fallback으로 유지한다.
- 운영 품질의 프롬프트는 DB `prompt_versions` 또는 private prompt pack으로 주입한다.

## Completion Checklist

작업이 코드, 문서, 설정, 테스트, 빌드 아티팩트를 바꾸면 final response 전에 다음을 확인한다.

1. 작업 성격에 맞는 검증을 실행하거나 명시적으로 생략한다.
2. 변경 요약, 핵심 파일, 검증 결과를 정리한다.
3. substantial work라면 [completion workflow](vaults/workflows/completion.md)에 따라
   worklog-ready 요약과 적절한 private 기록 위치를 결정한다.

## Closing The Loop

같은 사용자 수정이나 process gap이 두 번 이상 나타나면 chat에만 두지 않는다.
[vaults/durable/INDEX.md](vaults/durable/INDEX.md)에 가장 작은 public-safe 개선 기록을
남기고, root guide·task/workflow guide·decision note·재사용 skill 중 알맞은 더 좁은
source of truth로 승격한다.

## Git Safety

- 사용자가 만들었을 수 있는 변경은 되돌리지 않는다.
- destructive git 명령은 사용자가 명시적으로 요청한 경우에만 사용한다.
- 이 저장소가 git repository가 아닐 수도 있으므로 `git status` 실패를 정상 상황으로 취급한다.
