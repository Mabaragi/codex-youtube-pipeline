# Verification Workflow

검증은 변경 범위에 비례시킨다. 문서만 바뀌었다면 네트워크나 실제 Codex/YouTube/MinIO를
호출하지 않고, 경로·명령·구현 주장만 확인한다.

## Choose The Smallest Sufficient Check

1. 문서만 변경했으면 새 Markdown link 대상, 옛 경로·용어, `git diff --check`를
   확인한다. 명령이나 API 동작을 새로 서술했다면 대상 source·test·`--help`·OpenAPI 중
   가장 가까운 근거와 대조한다.
2. Python 코드나 설정을 바꿨으면 [docs/CICD.md](../../docs/CICD.md)의 local quality
   gates에서 변경 범위에 맞는 명령을 실행한다. 기본 backend suite는 `uv run pytest`,
   `uv run ruff check .`, `uv run pyrefly check --min-severity warn`,
   `uv run python scripts/export_openapi.py --check`다.
3. `ops-ui/`를 바꿨으면 [ops-ui verification](../../ops-ui/AGENTS.md#verification)의
   `api:check`, lint, typecheck, test, build을 따른다.
4. live credential, object storage, YouTube, Codex runtime, local worker가 필요한 smoke
   check는 자동 테스트와 분리한다. 사용자가 요청했거나 안전한 local context가 있을 때만
   실행하고, 실행하지 않았다면 이유를 final response에 남긴다.

## Documentation Integrity Checks

- 이동·rename 뒤에는 `rg -n "<old-path-or-term>" .`로 stale reference가 없는지
  확인한다.
- 새 문서는 가장 가까운 index 또는 guide에서 링크한다. index 항목은 무엇을 담고, 언제
  읽으며, 어떤 결정을 돕는지 한 문장으로 설명한다.
- 기존 dirty worktree를 발견하면 unrelated change를 되돌리지 않는다. 같은 파일을
  고쳐야 할 때는 최소 문맥 patch로 추가·정정하고 `git diff`에서 기존 변경이 보존됐는지
  확인한다.
