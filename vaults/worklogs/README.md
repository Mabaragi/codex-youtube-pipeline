# Private Worklog Fallback

실제 월별 worklog는 `vaults/worklogs/YYYY-MM.md` 형식으로 만든다. 이 디렉터리의
월별 Markdown 파일은 `.gitignore` 처리되어 public repository에 commit되지 않는다.
external worklog integration이 있으면 그것을 우선하고, 이 fallback은 local 기록이
필요할 때만 사용한다.

각 entry는 local date와 분 단위 시간을 포함한다.

```md
## YYYY-MM-DD HH:mm - 짧은 제목

완료: <작업 요약>
아티팩트: <핵심 파일, 문서, PR, screenshot 경로>
검증: <실행한 검증 또는 미실행 사유>
```

API key, token, private URL, raw transcript, raw LLM trace, 고객 데이터, 내부 운영
세부사항은 기록하지 않는다.
