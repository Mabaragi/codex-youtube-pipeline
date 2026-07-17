# Ops UI v2 Interface Rules

Ops UI는 한국어 고밀도 운영 화면이다. 장식용 landing page 요소보다 상태 비교와 안전한
조작을 우선한다.

## 시각 체계

- `globals.css`의 semantic OKLCH token만 사용한다. light/dark는 `next-themes`의 system
  기본값을 따른다.
- 공통 surface는 `Panel`, 상태는 `StatusBadge`, 조작은 CVA 기반 `Button`을 사용한다.
- 식별자, error code, model, task type은 monospace와 `translate="no"`를 유지한다.
- 숫자와 시간은 `Intl`과 tabular number로 표시한다.
- 거대한 page component 대신 screen, feature API, source-owned component로 나눈다.

## 상태와 입력

- loading, background refresh, empty, error는 별도 상태로 표시한다.
- background refresh 중 검색·필터 control DOM을 교체하지 않는다. focus, selection,
  caret를 보존해야 한다.
- destructive action은 즉시 실행하지 않는다. 대상 재입력, 운영 사유, pending 중 중복
  제출 방지를 적용한다.
- error는 조작 근처의 `role="alert"`, background refresh는 `aria-live` status로 알린다.

## 접근성

- skip link, `header`/`nav`/`main`, 페이지당 하나의 `h1`, 순차 heading을 사용한다.
- 모든 icon button에 접근 가능한 이름을 제공한다.
- `focus-visible` ring을 유지하며 dialog는 focus trap과 trigger 복귀를 보장한다.
- 모바일 control은 최소 44px 높이이며 가로 overflow surface는 명시적으로 스크롤한다.
- `prefers-reduced-motion`에서는 animation과 transition을 최소화한다.
- placeholder만으로 label을 대신하지 않는다.

새 UI 변경은 Vercel Web Interface Guidelines의 focus, form, async state, routing,
dialog 규칙을 정적 기준으로 검토한다.
