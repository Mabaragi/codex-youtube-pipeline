# 장시간 파이프라인을 안전하게 멈추려면 drain 상태가 필요하다

Date: 2026-07-14

## Context

이 프로젝트의 로컬 런타임은 API 하나가 아니라 scheduler, supervisor, 여러 worker,
workflow coordinator, PostgreSQL, MinIO로 구성된다. ASR과 micro-event 작업은 오래
실행되며 중간 체크포인트를 남긴다. 따라서 모든 프로세스를 한꺼번에 종료하는 방식은
단순해 보여도 다음 시작에서 만료 lease 복구, 중복 claim, 불필요한 재처리를 유발할 수
있다.

## What We Learned

### 프로세스 생존과 운영 상태는 다른 문제다

PID 파일은 특정 프로세스가 살아 있는지만 알려준다. 반면 “새 작업은 받지 말고 이미
시작한 작업만 끝내라”는 의도는 scheduler와 모든 claim 경로가 공유해야 한다. 이
의도는 PostgreSQL의 `active`, `draining`, `stopped` 상태로 저장해야 재시작과 여러
프로세스 사이에서도 유지된다.

### drain은 모든 쓰기를 막는 정지가 아니다

`draining`은 새 scheduler enqueue, workflow claim, work-item claim, inline 실행을
막는다. 이미 실행 중인 작업의 heartbeat, ASR chunk와 micro-event window
체크포인트, 성공·실패 저장, supervisor의 만료 lease 정리는 계속 허용한다. 이 구분이
있어야 작업이 자연스럽게 0건으로 수렴한다.

### timeout과 force는 서로 다른 운영 판단이다

기본 stop은 drain을 요청하고 `runningWorkItemCount == 0` 및
`runningWorkflowCount == 0`을 기다린다. 30분이 지나도 작업이 남아 있으면
프로세스를 살려 둔 채 실패를 반환한다. 이는 종료 실패라기보다 “아직 안전하게 끌 수
없다”는 신호다.

`-Force`는 즉시 프로세스를 종료하지만 상태를 `stopped`로 가장하지 않는다. 다음
start도 자동 resume하지 않으므로, 운영자가 체크포인트와 lease 복구 상태를 확인한 뒤
명시적으로 resume해야 한다.

### 시작·종료 순서도 계약의 일부다

시작은 PostgreSQL/MinIO, API, supervisor와 worker, coordinator, 필요 시 resume,
scheduler 순서다. 종료는 drain, 상태 확인, stopped 기록, native process 종료
순서다. 독점 잠금은 서로 다른 start/stop/restart 명령이 동시에 실행되는 것을 막고,
command line과 저장소 경로 검증은 PID 재사용으로 다른 프로세스를 종료하는 일을
막는다.

## Evidence

- 상태 전이와 `readyToStop` 조건은 runtime API와 PostgreSQL repository 테스트로
  검증했다.
- scheduler, workflow, worker, inline claim이 `draining/stopped`에서 차단되고 기존
  heartbeat와 완료 저장은 유지되는지 검증했다.
- PowerShell fake 테스트에서 정상 stop, timeout 유지, force, API 장애, infra 선택
  종료, 동시 명령 잠금을 검증했다.
- 실제 로컬 런타임에서 `drain -> stopped -> start(정지 유지) -> resume` canary를
  수행하고 PostgreSQL/MinIO가 기본 stop에서 유지되는 것을 확인했다.

## Implications

- 일상 운영은 [`runtime.ps1`](../../../scripts/local-home/runtime.ps1)을 단일 진입점으로
  사용한다.
- API가 꺼져 있으면 안전한 상태 전이를 확인할 수 없으므로 기본 stop을 계속 진행하지
  않는다.
- 예약 start나 반복 배포가 저장된 `draining/stopped` 상태를 임의로 `active`로
  바꾸면 안 된다.
- 데이터베이스·큐·아티팩트 삭제는 런타임 종료와 별개의 위험한 작업이며 이
  오케스트레이터가 제공하지 않는다.

## Related

- [Local native deployment](../../LOCAL_NATIVE_DEPLOYMENT.md)
- [Agent work runbooks](../../AGENT_WORK_RUNBOOKS.md)
- [Runtime API operations](../../AGENT_API_OPERATIONS.md)
- [Architecture decision](../../../vaults/decisions/2026-07-14-drain-based-local-runtime-orchestration.md)
