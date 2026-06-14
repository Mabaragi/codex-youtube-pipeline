# Docs Index

이 문서는 프로젝트를 이해하고 운영하기 위한 human-facing 문서의 라우팅 맵이다.
Agent-facing 지침은 루트 `AGENTS.md`와 `vaults/`를 사용한다.

- `docs/PROJECT_OVERVIEW.md`: 프로젝트 구조, CLI/FastAPI 동작, 실행/검증 방법을 설명한다. 프로젝트를 처음 보는 개발자나 사용자가 읽는다.
- `docs/CICD.md`: 현재 GitHub Actions, Docker Publish, Windows home PC self-hosted runner 배포 구조를 설명한다. CI/CD 전체 흐름, Mermaid 도표, 재부팅 후 배포 절차, 실패 대응을 확인할 때 읽는다.
- `docs/AWS_DEPLOYMENT.md`: Terraform, EC2, SSM, S3 Mountpoint 기반 AWS 배포 절차를 설명한다. 현재 main push 자동 배포 대상은 아니지만 AWS 배포를 다시 켜거나 참고할 때 읽는다.
- `docs/HOME_PC_DEPLOYMENT.md`: Windows PC self-hosted runner, Docker Compose, Nginx Basic Auth, Cloudflare quick tunnel로 API를 내 PC에서 배포하는 절차를 설명한다. YouTube transcript endpoint를 cloud IP block 없이 운영하려는 경우 읽는다.
