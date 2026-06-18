# Docs Index

이 문서는 프로젝트를 이해하고 운영하기 위한 human-facing 문서의 라우팅 맵이다.
Agent-facing 지침은 루트 `AGENTS.md`와 `vaults/`를 사용한다.

- `docs/PROJECT_OVERVIEW.md`: 프로젝트 구조, CLI/FastAPI 동작, 실행/검증 방법을 설명한다. 프로젝트를 처음 보는 개발자나 사용자가 읽는다.
- `docs/YOUTUBE_DATA_PIPELINE.md`: YouTube channel resolve부터 videos/transcripts/LLM summary까지 이어지는 데이터 파이프라인의 공통 상태 추적, raw 저장, domain row 연결 규칙을 설명한다.
- `docs/YOUTUBE_DATA_PIPELINE_TODO.md`: YouTube Data pipeline 설계를 따르는 남은 구현 backlog를 정리한다.
- `ops-ui/docs/FRONTEND_ARCHITECTURE.md`: Next.js 운영 UI 구조, BFF, 상태 관리, 화면 구성을 설명한다.
- `ops-ui/docs/API_CONTRACT.md`: FastAPI OpenAPI export와 frontend generated type 갱신 절차를 설명한다.
- `docs/CICD.md`: 현재 GitHub Actions, Docker Publish, Windows home PC self-hosted runner 배포 구조를 설명한다. CI/CD 전체 흐름, Mermaid 도표, 재부팅 후 배포 절차, 실패 대응을 확인할 때 읽는다.
- `docs/AWS_DEPLOYMENT.md`: Terraform, EC2, SSM, S3 Mountpoint 기반 AWS 배포 절차를 설명한다. 현재 main push 자동 배포 대상은 아니지만 AWS 배포를 다시 켜거나 참고할 때 읽는다.
- `docs/HOME_PC_DEPLOYMENT.md`: Windows PC self-hosted runner, Docker Compose, Nginx Basic Auth, ngrok dev domain tunnel로 API를 내 PC에서 배포하는 절차를 설명한다. YouTube transcript endpoint를 cloud IP block 없이 운영하려는 경우 읽는다.
- `docs/HOME_DEPLOYMENT_FLOW.md`: main push 이후 CI 이미지 publish, GHCR pull, Home PC compose update, local-build fallback까지 현재 배포 방식 변경점을 구체적으로 설명한다.
