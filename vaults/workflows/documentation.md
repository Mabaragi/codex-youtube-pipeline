# Documentation Workflow

새 agent-facing 문서나 사람용 학습 문서를 만들고, 기존 문서를 이동·정리할 때 사용한다.
목표는 같은 규칙을 한 곳에서만 관리하고 다음 작업자가 필요한 문서만 선택해 읽게 하는
것이다.

## 1. 먼저 인벤토리한다

- root `AGENTS.md`, `vaults/INDEX.md`, `docs/INDEX.md`, 가까운 하위 `AGENTS.md`를 먼저
  확인한다.
- `rg --files -g 'AGENTS.md' -g 'agents.md' -g 'CLAUDE.md' -g 'README*' -g '.github/**'
  -g 'vaults/**' -g 'docs/**'`로 기존 경로와 naming convention을 찾는다.
- `git status --short`로 다른 작업자의 변경을 확인한다. 관련 없는 변경은 수정하거나
  정리하지 않는다.

## 2. 내용을 배치한다

| 내용 | 위치 | 이 위치를 선택하는 기준 |
| --- | --- | --- |
| 모든 작업이 따라야 하는 행동·안전 규칙 | `AGENTS.md` | 매번 읽지 않으면 오류가 생기는 짧은 규칙 |
| 문서 선택 안내 | `vaults/INDEX.md` | 무엇을 담고 언제 읽을지 설명하는 annotated route |
| 특정 영역의 반복 구현 규칙 | `vaults/agents/` 또는 가까운 하위 `AGENTS.md` | 같은 영역 작업에서 반복해 필요한 규칙; 실제 필요가 생길 때만 생성 |
| 반복 가능한 작업 절차 | `vaults/workflows/` | verification, completion, documentation처럼 여러 작업에서 재사용하는 절차 |
| 반복 교정·process gap | `vaults/durable/INDEX.md` | 두 번 이상 나타났거나 다음 작업의 오류를 줄이는 개선 후보 |
| 확정된 장기 architecture·workflow 결정 | `vaults/decisions/` | 배경·선택·결과를 다음 session도 알아야 하는 결정 |
| substantial work의 private fallback 기록 | `vaults/worklogs/YYYY-MM.md` | external worklog가 없고 local handoff가 필요할 때 |
| 공개 제품·운영·개발 설명 | `docs/` | 사람이 읽고 사용할 public-safe 설명 |
| 날짜에 묶인 발견·디버깅 기록 | `docs/learnings/notes/` | 아직 정제되지 않았거나 특정 작업 맥락이 중요한 학습 |
| 반복 참조할 정제된 설명 | `docs/learnings/topics/` | 여러 작업에 재사용할 개념, tradeoff, 비교, 해설 |
| 개인 또는 여러 저장소에 공통인 선호 | global skill/config | 이 저장소에만 적용되는 규칙이 아닐 때 |

secret, raw transcript·trace, production prompt, private URL·runbook은 public 문서나
tracked vault에 기록하지 않는다.

## 3. 한 source of truth로 연결한다

1. 기존 문서에 같은 규칙이 있는지 검색하고, 가장 좁고 지속 가능한 위치 한 곳을 고른다.
2. 새 문서는 가장 가까운 index에서 연결한다. 각 항목은 문서 내용, 읽을 시점, 지원하는
   작업 또는 결정을 한두 문장으로 설명한다.
3. root guide에는 상세 목록을 복제하지 않고 `vaults/INDEX.md`를 가리키는 짧은 route만
   둔다.
4. 사람용 학습 문서는 [learnings 안내](../../docs/learnings/README.md)에 따라 note와
   topic을 구분하고 [learnings index](../../docs/learnings/INDEX.md)에 연결한다.

## 4. 완료 전에 점검한다

- 새 Markdown link의 상대 경로와 대상 파일을 확인한다.
- rename·move가 있었다면 `rg -n '<old-path-or-term>' .`로 stale reference를 찾는다.
- `git diff --check`와 문서 diff를 확인한다. 문서만 바꿨다면 code formatter와 test
  suite는 실행하지 않는다.
- root bloat audit를 수행한다: 새 내용이 항상 읽혀야 하는지, project fact·endpoint
  목록·배포 상세·guide map을 index나 lazy-loaded guide로 옮길 수 있는지 확인한다.
- [completion workflow](completion.md)에 따라 요약, artifact, 검증, 기록 위치를
  마무리한다.
