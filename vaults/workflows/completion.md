# Completion Workflow

이 workflow는 코드, 문서, 설정, 테스트, build artifact에 substantial change가 있을 때
적용한다. 단순 질의·짧은 설명에는 필요한 결과만 답한다.

## Before The Final Response

1. [verification workflow](verification.md)에 따라 실행한 검증과 의도적으로 생략한
   검증을 구분한다.
2. 변경 요약, 핵심 artifact 경로, 검증 결과, 남은 제약 또는 decision을 짧게 정리한다.
3. 반복된 correction이나 재사용 가능한 process gap이 있었는지 판단한다. 있었다면
   [durable improvement index](../durable/INDEX.md)에 기록하거나 더 좁은 source of
   truth로 승격한다.
4. external worklog integration이 있으면 완료·artifact·검증 결과를 그곳에 남긴다.
   integration이 없으면 final response에 같은 세 항목을 포함해 worklog-ready summary로
   제공한다.

## Private File-Log Fallback

외부 worklog가 없고 local file 기록이 필요한 경우에만
`vaults/worklogs/YYYY-MM.md`에 local time 기준 entry를 추가한다. 월별 파일은 의도적으로
`.gitignore` 처리되어 있으며, public repository에는 commit하지 않는다. secret, raw
trace, 사용자 데이터, 운영 상세는 기록하지 않는다.

형식은 [worklog template](../worklogs/README.md)을 따른다.
