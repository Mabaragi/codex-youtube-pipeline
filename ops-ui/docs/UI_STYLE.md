# Ops UI Style Rules

`ops-ui`는 운영 콘솔이다. 새 화면은 마케팅 페이지처럼 보이면 안 되고,
반복 작업자가 빠르게 스캔하고 조작할 수 있는 조용한 업무 도구처럼 보여야
한다.

## Visual Direction

- 화면은 항상 실제 작업 화면으로 시작한다. hero, landing copy, 장식용
  illustration, gradient background를 만들지 않는다.
- 밀도는 높게 유지하되, 정보 그룹은 `gap-4`, `ops-panel`, table, section
  heading으로 분리한다.
- 팔레트는 `ops-ui/src/app/globals.css`의 CSS variables를 우선한다:
  `--background`, `--foreground`, `--muted`, `--line`, `--panel`, `--accent`,
  `--danger`, `--warning`, `--success`.
- 새 dominant color theme, 큰 gradient, decorative orb/blob, 강한 shadow,
  과한 rounded card를 추가하지 않는다.
- Border radius는 기존 `6px`/`rounded-md` 수준을 따른다. 반복 item이나
  inspector row는 `rounded border` 정도만 사용한다.

## Layout

- 새 page는 `PageHeader`로 시작하고, 주요 action은 header의 `actions` 영역이나
  table action cell에 둔다.
- data-heavy 화면은 `DataTable`과 TanStack Table을 기본으로 사용한다.
- 주요 surface는 `ops-panel`을 사용한다. `ops-panel` 안에 또 다른 큰
  `ops-panel`을 중첩하지 말고, 내부 구분은 `border-t`, `border-b`,
  `grid gap-*`, 작은 `rounded border` block으로 처리한다.
- page-level spacing은 `grid gap-4`, control cluster는 `flex flex-wrap gap-2`
  패턴을 우선한다.
- horizontal overflow가 생길 수 있는 table/tool surface는 `overflow-x-auto`,
  `min-w-0`, `truncate`, 명시적 `max-w-*`를 사용해 mobile에서 텍스트가
  겹치지 않게 한다.

## Components

- Button은 기본적으로 `ops-button`을 사용한다. 주요 실행 하나만
  `ops-button ops-button-primary`를 사용한다.
- Button에는 가능한 경우 `lucide-react` icon과 짧은 label을 함께 둔다.
  아이콘만 쓰는 control은 `title` 또는 접근 가능한 label을 제공한다.
- Input/select는 `ops-input`을 사용한다.
- Status 값은 `StatusBadge`로 표현한다. 새 status color를 만들기 전에
  `ops-status-ok`, `ops-status-warn`, `ops-status-bad`,
  `ops-status-muted` 중 하나로 매핑할 수 있는지 먼저 본다.
- 반복 table, badge, shell, header 동작을 page 안에서 새로 만들지 말고
  `components/`의 기존 공용 컴포넌트를 확장하거나 재사용한다.

## Typography

- Page title은 `PageHeader`의 `text-2xl font-semibold tracking-normal`을
  따른다.
- Compact panel heading은 `text-sm font-semibold`를 사용한다.
- Secondary metadata는 `text-xs text-slate-500` 또는 `text-slate-600`을
  사용한다.
- Table body는 기존 `ops-table`의 `13px` 기준을 유지한다.
- Font size를 viewport width에 따라 scale하지 않는다. Letter spacing은
  기본값 또는 `tracking-normal`을 사용하고 negative tracking은 쓰지 않는다.

## State And Feedback

- Loading은 기존 패턴인 `ops-panel p-4 text-sm text-slate-600`을 사용한다.
- Error는 `ops-panel p-4 text-sm text-red-700`을 기본으로 사용한다.
- 사용자가 누르면 long-running backend 작업이 시작되는 button은 pending,
  running, duplicate-run 방지 상태를 disabled로 반영한다.
- Disabled button은 왜 비활성화됐는지 `title`이나 근처 짧은 feedback text로
  알 수 있게 한다.
- 성공 후 server state가 바뀌면 관련 TanStack Query key를 invalidate한다.

## Copy

- 화면 안 설명문은 짧게 쓴다. 기능 설명을 길게 적지 말고, 상태와 필요한
  다음 행동만 보여준다.
- Button label은 `Videos`, `Transcripts`, `Retry job`처럼 동작 중심으로
  짧게 쓴다.
- Empty/loading/error text는 기존 문체를 따른다: `No rows.`, `Loading...`,
  `No recent failures.` 같은 간단한 문장.
