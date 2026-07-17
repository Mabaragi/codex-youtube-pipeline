# 로컬 런타임은 drain 후 종료한다

## Rule

실행 중인 로컬 파이프라인을 유지보수, 배포, 재시작하기 전에 프로세스를 직접
종료하지 않는다. `runtime.ps1 stop` 또는 runtime drain API로 새 enqueue와 claim을
먼저 막고, 상태 API의 `readyToStop`이 참이 된 뒤 `stopped`를 기록해 종료한다.

timeout이 발생하면 프로세스와 `draining` 상태를 유지한다. 자동으로 강제 종료하거나
자동 resume하지 않는다. `-Force`는 체크포인트·lease 복구가 필요할 수 있음을
운영자가 수용한 경우에만 사용한다. 데이터 삭제를 안전 종료의 대체 수단으로 쓰지
않는다.

## Why

PID나 프로세스 상태만으로는 scheduler, worker, workflow coordinator가 공유할 운영
의도를 표현할 수 없다. 데이터베이스에 저장된 drain 상태가 있어야 여러 실행 주체가
동시에 새 작업을 멈추면서 기존 작업의 heartbeat와 완료 저장은 계속할 수 있다.

## Source Of Truth

구현 선택과 실패 의미는
[drain 기반 로컬 런타임 결정](../decisions/2026-07-14-drain-based-local-runtime-orchestration.md)에,
실행 명령은 [local native deployment](../../docs/LOCAL_NATIVE_DEPLOYMENT.md)에 있다.
