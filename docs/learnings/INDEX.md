# Learnings Index

사람이 다시 읽을 발견, debugging narrative, tradeoff, 재사용 가능한 설명을 찾는
annotated index다. 작성 위치와 형식은 [Human Learnings](README.md)를 따른다.

## Notes

- [Notes guide](notes/README.md): 날짜와 작업 맥락에 묶인 짧은 학습 기록의 naming과
  작성 범위를 설명한다. 새 debugging·discovery note를 남길 때 읽는다.

- [방송 구간 분류 실험](notes/2026-09-30-segment-category-classification.md):
  timeline 요약 위에서 저챗·게임·노래·같이보기·카페 탐방·준비·세팅·합방을 분류한
  taxonomy v1.6 규칙, 후처리, 정확도·안정성 결과, 파이프라인 구현 시 고려점을 정리한다.
  구간 분류 단계나 공개 segment 계약을 설계할 때 읽는다.

## Topics

- [Topics guide](topics/README.md): 여러 작업에서 반복 참조할 정제된 설명의 승격 기준과
  작성 범위를 설명한다. note를 통합하거나 재사용 가능한 해설을 만들 때 읽는다.
- [Drain 기반 로컬 런타임 오케스트레이션](topics/drain-based-local-runtime-orchestration.md):
  장시간 작업의 체크포인트를 보존하면서 새 작업만 차단하는 이유와
  `active/draining/stopped`, timeout, force의 운영 의미를 설명한다.
- [Work 종료 상태의 단일 소유권](topics/work-terminal-state-ownership.md):
  domain output 저장과 work item·attempt 종료를 분리해야 하는 이유, split ownership의
  장애 형태, adapter 구성과 검증 기준을 설명한다.
