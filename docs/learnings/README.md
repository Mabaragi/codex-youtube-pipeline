# Human Learnings

이 디렉터리는 개발자가 나중에 다시 읽을 public-safe 학습 자료를 보관한다. 구현 중 발견한
사실, 디버깅 과정에서 얻은 교훈, 선택지의 tradeoff, 반복해서 설명할 개념을 기록한다.

## 무엇을 어디에 쓸지

- 특정 날짜·작업 맥락이 중요한 짧은 발견은 `notes/YYYY-MM-DD-short-title.md`에 쓴다.
- 여러 작업에서 재사용할 수 있도록 정제한 설명은 `topics/short-title.md`에 쓴다.
- note가 반복해서 인용되거나 맥락 없이도 유효해지면 topic으로 통합하고 원래 note에서
  연결한다.

작업 상태와 검증 결과는 worklog, agent 행동 규칙과 handoff context는 `AGENTS.md`와
`vaults/`, 확정된 장기 결정은 `vaults/decisions/`에 둔다. secret, private 운영 정보,
raw transcript·LLM trace, production prompt는 이곳에 기록하지 않는다.

## 공통 작성 규칙

1. 제목과 날짜, 학습이 필요했던 맥락을 짧게 적는다.
2. 관찰한 사실과 추론을 구분하고 source code, test, public 문서 같은 근거를 연결한다.
3. 재현 조건, tradeoff, 다음 구현에 미치는 영향을 독자가 판단할 수 있게 적는다.
4. 새 문서는 [INDEX.md](INDEX.md)에 한 줄 요약과 함께 연결한다.

```md
# 제목

Date: YYYY-MM-DD

## Context

## What We Learned

## Evidence

## Implications

## Related
```
