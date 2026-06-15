# Agents Guide

## Project

이 저장소는 Python으로 만든 `codex-demo` CLI 예제 프로젝트다. OpenAI Codex Python SDK인 `openai-codex`를 사용해 Codex thread를 시작하거나 재개하고, 로그인과 계정 상태 확인을 수행한다.

## Context Vault

상세 문서는 `vaults/INDEX.md`에서 라우팅한다. 루트 문서는 항상 지켜야 할 규칙만 담고, 구현 세부사항과 반복 workflow는 vault 문서를 읽는다.

## Suggested Reading Order

1. 이 `AGENTS.md`.
2. `vaults/INDEX.md`.
3. 작업에 맞는 `vaults/agents/` 또는 `vaults/workflows/` 문서.
4. 대상 코드와 관련 테스트.
5. 결정 기록은 해당 영역을 바꾸는 작업일 때만 읽는다.

## Always Follow

- 새 Python 코드는 `modern-python` 기본값을 따른다: `src/` layout, Click CLI, `pydantic-settings`, Protocol 기반 경계, pytest/Ruff/Pyrefly 검증.
- CLI command 함수는 얇게 유지하고, Codex SDK 호출과 use-case 로직은 `src/codex_sdk_cli/runner.py`에 둔다.
- 환경 설정은 `src/codex_sdk_cli/settings.py`의 `CliSettings`와 `CODEX_CLI_` prefix를 통해 관리한다.
- DB schema 변경은 SQLAlchemy 모델과 Alembic migration으로만 수행하고, 앱 코드나 테스트에서 `metadata.create_all()`/`drop_all()`을 호출하지 않는다.
- 자동 테스트에서는 실제 Codex app-server, 로그인, 네트워크 호출을 띄우지 않는다. Protocol/fake 기반 테스트를 사용한다.
- `openai-codex`는 베타 SDK이며 prerelease runtime dependency가 필요하므로 `[tool.uv] prerelease = "allow"`를 유지한다.

## Completion Checklist

작업이 코드, 문서, 설정, 테스트, 빌드 아티팩트를 바꾸면 final response 전에 다음을 확인한다.

1. 작업 성격에 맞는 검증을 실행하거나 명시적으로 생략한다.
2. 변경 요약, 핵심 파일, 검증 결과를 정리한다.
3. 큰 작업이면 worklog workflow에 따라 `vaults/worklogs/YYYY-MM.md`에 기록한다.
4. 반복되는 사용자 수정이나 작업 교훈은 chat에만 두지 말고 가장 작은 durable 문서에 반영한다.

## Task Guides

- `vaults/agents/python-cli.md`: CLI 명령, 설정, SDK adapter, 테스트 경계를 바꾸는 작업에서 읽는다.
- `vaults/agents/database.md`: SQLite, SQLAlchemy 모델, DB 세션, Alembic migration을 바꾸는 작업에서 읽는다.

## Workflow Guides

- `vaults/workflows/verification.md`: 어떤 검증을 실행할지 결정할 때 읽는다.
- `vaults/worklogs/README.md`: substantial work의 local worklog fallback 규칙을 확인할 때 읽는다.

## Human-Facing Docs

사용자나 개발자가 프로젝트를 이해하기 위한 문서는 `docs/`에 둔다. agent는 필요한 경우 `docs/INDEX.md`에서 어떤 문서를 읽을지 확인한다.

## Closing The Loop

같은 지적이나 수정이 두 번 이상 반복되면 chat에서만 처리하지 않는다. 루트 guide, task guide, workflow guide, decision note, 또는 reusable skill 중 가장 작은 위치에 규칙을 추가한다.

## Git Safety

- 사용자가 만들었을 수 있는 변경은 되돌리지 않는다.
- destructive git 명령은 사용자가 명시적으로 요청한 경우에만 사용한다.
- 이 저장소가 git repository가 아닐 수도 있으므로 `git status` 실패를 정상 상황으로 취급한다.
