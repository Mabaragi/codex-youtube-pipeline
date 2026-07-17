# Work 종료 상태의 단일 소유권

Date: 2026-07-16

## Context

통합 work model에서는 domain use case가 과거의 task·job 형태 port를 계속 사용할 수 있다.
실제 저장 대상은 `work_items`와 `work_attempts` 하나뿐이므로 호환 adapter와
`WorkExecutionEngine`이 같은 실행 상태를 동시에 완료하면 안 된다.

Archive publish처럼 domain output을 별도 transaction에서 저장하는 inline 작업은 이
경계를 놓치기 쉽다. 객체와 artifact row는 이미 생성됐는데 API가 상태 전이 충돌을
반환하거나, 성공한 work item 아래 최신 attempt가 계속 `running`으로 남을 수 있다.

## What We Learned

현재 실행의 terminal transition은 `WorkExecutionEngine`만 소유한다.

- Executor와 domain use case는 artifact, provenance, domain output을 저장하고 결과를
  `WorkExecutionResult`로 반환한다.
- Engine은 반환된 결과로 work attempt와 work item을 같은 Unit of Work에서 완료한다.
- 호환 adapter는 현재 `work_item_id`와 `work_attempt_id`를 받았을 때 terminal record를
  투영해 반환할 수 있지만, 현재 실행 row를 먼저 변경하지 않는다.
- `WorkVideoTaskRepository`와 `WorkPipelineJobRepository`에는 동일한 현재 실행 ID를
  함께 전달한다. 한쪽만 execution-aware로 구성하면 split ownership이 다시 생긴다.

이 원칙은 “이미 succeeded면 다시 complete해도 된다”는 식의 전역 멱등 처리로 대체하지
않는다. 그런 완화는 lease 상실이나 다른 worker의 완료까지 정상 중복으로 오인할 수 있다.
상태 소유권을 composition root에서 명확히 하는 편이 안전하다.

## Failure Signature

다음 조합은 data plane은 성공했지만 control plane이 일관되지 않다는 신호다.

- R2 객체와 archive artifact row가 존재한다.
- API가 `work_item.transition_not_allowed` 같은 완료 충돌을 반환한다.
- work item은 `succeeded`인데 최신 attempt는 `running`이다.

이때 artifact 존재만 보고 성공으로 확정하거나 즉시 같은 요청을 반복하지 않는다. work
상세와 API 로그를 확인하고 adapter 구성을 바로잡는다. 프로세스가 중단된 inline attempt는
startup recovery가 명시적인 중단 오류로 terminal 처리한 뒤 재실행한다.

## Evidence

- [`WorkExecutionEngine`](../../../src/codex_sdk_cli/application/work/execution.py)은 attempt와
  item 완료를 하나의 Unit of Work에서 기록한다.
- [`archive_publish_execution_use_case`](../../../src/codex_sdk_cli/bootstrap/archive.py)는
  archive 실행에 필요한 두 호환 adapter에 같은 현재 실행 ID를 전달한다.
- [`test_archive_publish_execution_adapters_defer_current_status_to_engine`](../../../tests/test_archive_publish.py)은
  이 composition 계약을 회귀 검사한다.

## Implications

새 executor를 추가하거나 legacy-shaped use case를 통합할 때 다음을 확인한다.

1. 현재 실행을 나타내는 모든 compatibility adapter가 같은 item·attempt ID를 받는가?
2. Domain 성공 처리 후에도 DB의 현재 item과 attempt가 engine 완료 전까지 `running`인가?
3. Engine 완료 후 item과 최신 attempt가 함께 terminal이고 output이 일치하는가?
4. API 성공 응답, artifact read model, public catalog 상태를 함께 검증하는가?

## Related

- [Clean Architecture](../../CLEAN_ARCHITECTURE.md)
- [R2 Archive Publish](../../ARCHIVE_PUBLISH.md)
- [Agent Work Runbooks](../../AGENT_WORK_RUNBOOKS.md)
