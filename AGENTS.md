# Agents Guide

## Project

이 저장소는 Python `codex-demo` CLI와 `codex-api` FastAPI 예제 프로젝트다. 현재 기능, 배포 방식, task guide 라우팅은 `vaults/INDEX.md`에서 확인한다.

## Context Vault

상세 문서는 `vaults/INDEX.md`에서 라우팅한다. 루트 문서는 항상 지켜야 할 규칙만 담고, 구현 세부사항과 반복 workflow는 vault 문서를 읽는다.
운영 UI 프론트엔드 작업은 `ops-ui/AGENTS.md`를 먼저 읽고, 백엔드 내부 문서는 API contract나 배포 경계를 바꿀 때만 추가로 읽는다.
사용자가 코드베이스 탐색 없이 운영 API만 호출하라고 요청한 에이전트는 `docs/AGENT_API_OPERATIONS.md`를 먼저 읽고, 소스 코드 검색 대신 해당 문서와 `/openapi.json`만 사용한다.

## Suggested Reading Order

1. 이 `AGENTS.md`.
2. `vaults/INDEX.md`.
3. 작업에 맞는 `vaults/agents/` 또는 `vaults/workflows/` 문서.
4. 대상 코드와 관련 테스트.
5. 결정 기록은 해당 영역을 바꾸는 작업일 때만 읽는다.

## Always Follow

- 새 Python 코드는 `modern-python` 기본값과 이 저장소의 domain-first 구조를 따른다.
- CLI command 함수와 FastAPI route handler는 얇게 유지하고, 세부 경계는 `vaults/agents/` guide를 따른다.
- 환경 설정은 `src/codex_sdk_cli/settings.py`의 `CliSettings`와 `CODEX_CLI_` prefix를 통해 관리한다.
- DB schema 변경은 SQLAlchemy 모델과 Alembic migration으로만 수행하고, 앱 코드나 테스트에서 `metadata.create_all()`/`drop_all()`을 호출하지 않는다.
- 자동 테스트에서는 실제 Codex app-server, 로그인, YouTube, MinIO, 네트워크 호출을 띄우지 않는다. Protocol/fake 기반 테스트를 사용한다.
- `openai-codex`는 베타 SDK이며 prerelease runtime dependency가 필요하므로 `[tool.uv] prerelease = "allow"`를 유지한다.

## Completion Checklist

작업이 코드, 문서, 설정, 테스트, 빌드 아티팩트를 바꾸면 final response 전에 다음을 확인한다.

1. 작업 성격에 맞는 검증을 실행하거나 명시적으로 생략한다.
2. 변경 요약, 핵심 파일, 검증 결과를 정리한다.
3. 큰 작업이면 worklog workflow에 따라 `vaults/worklogs/YYYY-MM.md`에 기록한다.
4. 반복되는 사용자 수정이나 개선사항은 chat에만 두지 말고 `vaults/durable/INDEX.md`를 따라 기록하거나 반영한다.

## Closing The Loop

같은 지적이나 수정이 두 번 이상 반복되면 chat에서만 처리하지 않는다. 먼저 `vaults/durable/INDEX.md`를 읽고, 그 절차에 따라 반복 개선사항을 기록하거나 가장 작은 source of truth로 승격한다.

## Git Safety

- 사용자가 만들었을 수 있는 변경은 되돌리지 않는다.
- destructive git 명령은 사용자가 명시적으로 요청한 경우에만 사용한다.
- 이 저장소가 git repository가 아닐 수도 있으므로 `git status` 실패를 정상 상황으로 취급한다.
