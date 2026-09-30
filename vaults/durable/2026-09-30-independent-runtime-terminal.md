# 운영 런타임은 별도 Windows Terminal에서 실행한다

## Rule

운영 API와 워커를 시작하거나 재시작할 때 별도 Windows Terminal 창에서
`runtime.ps1`을 실행한다. 창과 워커의 프로세스 계보가 에이전트 앱과 분리됐는지,
API가 healthy인지, 필요한 워커가 실행 중인지 확인한다. 사용자 요청 없이 예약 작업이나
Windows 서비스로 운영 방식을 변경하지 않는다.

## Why

숨겨진 백그라운드 프로세스를 시작했다고 앱 종료 이후의 생존이 보장되는 것은 아니다.
운영자가 볼 수 있는 독립 터미널에서 실행하고, 종료와 재시작에는 기존 drain 절차를
사용한다.

## Source Of Truth

[local native deployment](../../docs/LOCAL_NATIVE_DEPLOYMENT.md)의 실행 명령과
[안전 종료 규칙](2026-07-14-safe-local-runtime-shutdown.md)을 함께 따른다.
