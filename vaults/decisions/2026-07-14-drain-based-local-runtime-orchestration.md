# Drain 기반 로컬 런타임 오케스트레이션

Date: 2026-07-14

## Context

로컬 파이프라인에는 ASR chunk와 micro-event window처럼 오래 실행되며 체크포인트를
남기는 작업이 있다. 프로세스만 즉시 종료하면 새 claim이 계속 유입되는 동안 기존
lease가 끊길 수 있고, 재시작 시 실제 운영 의도와 무관하게 작업이 다시 시작될 수
있다. PID 파일은 프로세스 생존 여부는 알려주지만 scheduler, worker, workflow가
공유해야 하는 운영 의도까지 표현하지 못한다.

## Decision

- `backfill/steady` 자동화 모드와 별개로 PostgreSQL에 `active`, `draining`,
  `stopped` 런타임 상태를 저장한다.
- `draining`과 `stopped`에서는 scheduler enqueue, workflow claim, work-item
  claim, inline 실행을 차단한다. 이미 실행 중인 작업의 heartbeat, 체크포인트,
  성공·실패 저장과 supervisor의 lease 정리는 허용한다.
- 정상 종료는 `active -> draining -> stopped` 순서만 사용한다.
  `runningWorkItemCount`와 `runningWorkflowCount`가 모두 0이 되기 전에는
  `mark-stopped`를 거부한다.
- `runtime.ps1`을 로컬 프로세스의 단일 운영 진입점으로 사용한다. 기본 `stop`은
  30분 동안 drain을 기다리고, 제한 시간을 넘기면 강제 종료하지 않은 채
  `draining`으로 남긴다.
- 강제 종료는 명시적인 `-Force`에서만 허용한다. 강제 종료 후에는 자동 resume하지
  않으며 운영자가 복구 상태를 확인한 뒤 명시적으로 resume한다.
- 기본 종료는 PostgreSQL과 MinIO를 유지한다. 데이터베이스·큐·아티팩트를 지우는
  초기화 기능은 제공하지 않는다.
- 동시 start/stop/restart는 독점 잠금으로 막고, 프로세스 종료 전 command line과
  저장소 경로를 확인해 PID 재사용으로 인한 오종료를 방지한다.

## Consequences

- 정상 유지보수와 배포는 실행 중 작업을 보존하면서 새 작업 유입을 멈출 수 있다.
- 안전한 종료에는 API와 PostgreSQL이 필요하다. API가 없으면 정상 stop은 실패하며
  운영자가 `-Force` 여부를 명시적으로 판단해야 한다.
- stop timeout은 실패가 아니라 아직 drain이 끝나지 않았다는 운영 상태를 의미한다.
  프로세스를 살려 둔 채 나중에 상태를 다시 확인할 수 있다.
- 예약 실행이나 반복 start는 저장된 `draining/stopped` 의도를 덮어쓰지 않는다.
- Windows 서비스 자동 등록과 프로세스 감독 체계 교체는 이 결정의 범위에 포함하지
  않는다.

## Links

- [Local native deployment](../../docs/LOCAL_NATIVE_DEPLOYMENT.md)
- [Agent work runbooks](../../docs/AGENT_WORK_RUNBOOKS.md)
- [Runtime API operations](../../docs/AGENT_API_OPERATIONS.md)
- [Design learning](../../docs/learnings/topics/drain-based-local-runtime-orchestration.md)
- [`runtime.ps1`](../../scripts/local-home/runtime.ps1)
