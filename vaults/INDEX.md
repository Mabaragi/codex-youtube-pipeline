# Agent Context Vault

이 디렉터리는 `AGENTS.md`를 읽은 뒤 작업에 필요한 에이전트용 컨텍스트만 추가로
불러오기 위한 라우터다. 사람을 위한 제품·운영 설명은 `docs/`에 두며, private
runbook·실행 로그·secret은 이 디렉터리에 기록하지 않는다.

## Workflow Guides

- [verification workflow](workflows/verification.md): 코드·문서·설정·frontend 변경에
  알맞은 검증 범위를 고른다. final response 전에 무엇을 실행하거나 생략할지 결정할 때
  읽는다.
- [completion workflow](workflows/completion.md): substantial work의 완료 요약, artifact,
  검증 결과, private worklog fallback을 정리한다. 작업을 마무리하거나 handoff할 때 읽는다.
- [durable improvement index](durable/INDEX.md): 반복된 사용자 교정과 재사용 가능한
  process gap을 기록·승격하는 기준이다. 같은 종류의 교정이 두 번 이상 나타날 때 읽는다.
- [private worklog template](worklogs/README.md): external worklog integration이 없을 때
  사용하는 월별 private fallback 형식이다. 실제 월별 파일은 `.gitignore`로 보호된다.

## Project Context

- [public documentation index](../docs/INDEX.md): 제품 구조, API, 배포, architecture
  linting, archive publish 등 사람도 읽는 공개 문서를 작업별로 찾는다. 구현 배경이나
  public API를 바꿀 때 읽는다.
- [API operation reference](../docs/AGENT_API_OPERATIONS.md): local pipeline을 API로
  조작할 때의 public-safe endpoint catalog다. API-only 진단·실행의 endpoint와 입력을
  결정할 때 읽는다.
- [pipeline operation runbooks](../docs/AGENT_WORK_RUNBOOKS.md): pipeline 실행, 재시도,
  publish, artifact 검증의 단계별 절차다. 실제 운영 작업 요청일 때 읽는다.
- [Ops UI agent guide](../ops-ui/AGENTS.md): Next.js UI, BFF, generated contract, frontend
  verification 경계를 정한다. `ops-ui/`를 바꿀 때 root guide 다음에 읽는다.

## Boundary Rules

- 이 vault는 에이전트 작업 방식과 라우팅만 다룬다. 학습·디버깅 서술처럼 사람이 다시
  읽을 자료는 `docs/`의 주제 문서에 둔다.
- 장기적인 architecture 또는 workflow 결정이 실제로 생기면 `vaults/decisions/`에
  날짜 기반 note를 추가하고 이 index에 링크한다. 빈 decision 디렉터리는 만들지 않는다.
- `docs/AGENT_API_OPERATIONS.md`와 `docs/AGENT_WORK_RUNBOOKS.md`는 기존 경로와
  다른 작업자의 변경을 보존하기 위해 이동하거나 복제하지 않는다. 새 agent-facing
  문서는 이 vault에서 라우팅한다.
