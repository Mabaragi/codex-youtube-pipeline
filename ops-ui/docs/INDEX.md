# Ops UI Docs Index

`ops-ui` 작업자는 `ops-ui/AGENTS.md`를 먼저 읽고, 아래 문서 중 작업에 맞는
것만 추가로 읽는다. 상세 코드는 문서가 가리키는 경계와 파일을 확인한 뒤에
연다.

- [Frontend architecture](FRONTEND_ARCHITECTURE.md): Next.js App Router 운영 콘솔의
  runtime shape, state ownership, 화면 구성을 설명한다. 화면 구조, 상태 관리,
  라우팅, React Flow ERD 경계를 바꿀 때 읽는다.
- [UI style](UI_STYLE.md): 운영 콘솔의 visual direction, layout,
  component reuse, typography, feedback 규칙을 설명한다. 새 화면, UI component,
  table, form, action button, 상태 표시를 만들거나 고칠 때 읽는다.
- [BFF proxy](BFF_PROXY.md): 브라우저 요청이 Next BFF
  `/ops/api/backend/*`를 거쳐 FastAPI로 전달되는 방식을 설명한다. API 호출,
  proxy route, 배포 환경 변수, BFF health check를 바꿀 때 읽는다.
- [API contract](API_CONTRACT.md): FastAPI OpenAPI schema에서 생성되는 frontend
  contract 파일과 검증 명령을 설명한다. backend endpoint shape, generated type,
  API client 사용 방식을 바꿀 때 읽는다.
