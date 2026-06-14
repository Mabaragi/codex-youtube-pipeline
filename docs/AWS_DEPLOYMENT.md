# AWS 배포 가이드

이 프로젝트의 `codex-demo` CLI는 Python package로 빌드한 뒤 AWS EC2에 설치할 수 있다. Terraform root module은 `infra/aws-codex-cli`에 있다.

## 배포 구조

- Terraform이 wheel artifact를 private S3 bucket에 업로드한다.
- EC2 instance는 SSM Session Manager로 접속한다. 기본 SSH ingress는 없다.
- EC2 user-data가 `uv`, `codex-demo`, Mountpoint for Amazon S3를 설치한다.
- Codex 로그인 상태와 thread 상태는 EC2에서 CLI를 실행한 Linux user의 로컬 `~/.codex`에 저장된다.

## 실행

먼저 AWS CLI 세션을 확인한다.

```powershell
aws sts get-caller-identity --region ap-northeast-2
```

세션이 만료됐으면 로컬 PowerShell에서 로그인한다.

```powershell
aws login --remote --region ap-northeast-2
```

검증과 plan까지:

```powershell
.\scripts\deploy_aws.ps1
```

실제 생성까지:

```powershell
.\scripts\deploy_aws.ps1 -Apply
```

기본 region은 `ap-northeast-2`다. 변경하려면:

```powershell
.\scripts\deploy_aws.ps1 -Region us-east-1 -Apply
```

## 접속과 확인

Terraform output의 `ssm_start_session_command`를 실행한다.

```powershell
aws ssm start-session --target <instance-id> --region <region>
```

인스턴스 안에서:

```bash
codex-demo --help
codex-demo login device
codex-demo account
```

## S3 데이터를 Codex가 탐색하게 하기

Terraform apply 때 읽을 bucket ARN을 넘긴다.

```powershell
terraform -chdir=infra/aws-codex-cli apply `
  -var 'read_only_s3_bucket_arns=["arn:aws:s3:::my-data-bucket"]'
```

인스턴스 안에서 Mountpoint for Amazon S3로 마운트한다.

```bash
sudo codex-s3-mount my-data-bucket /mnt/s3/my-data-bucket
codex-demo run --cwd /mnt/s3/my-data-bucket "이 데이터 구조를 분석해줘"
```

Mountpoint는 S3 object 접근용이다. 대량 small-file 탐색이나 빈번한 쓰기, rename-heavy 작업은 로컬 디스크와 다르게 느리거나 제한될 수 있다.

## Docker로 실행

EC2 또는 로컬 Docker 환경에서 CLI 이미지를 빌드한다.

```bash
docker build -t codex-sdk-cli .
docker run --rm codex-sdk-cli --help
```

S3 Mountpoint는 호스트에서 먼저 마운트하고, 컨테이너에는 bind mount로 전달한다.

```bash
sudo codex-s3-mount my-data-bucket /mnt/s3/my-data-bucket

docker run --rm \
  --mount type=bind,source=/mnt/s3/my-data-bucket,target=/data/s3,readonly \
  codex-sdk-cli \
  run --sandbox read-only "Read /data/s3/prompt.md and summarize it."
```

컨테이너 이미지는 Codex 로그인 상태나 API key를 포함하지 않는다. 인증 정보는 실행 시점에 환경 변수나 볼륨으로 주입한다.

일회성 컨테이너에서 ChatGPT 로그인 세션을 재사용하려면 named volume을
`/home/codex/.codex`에 붙인다.

```bash
docker volume create codex-sdk-cli-home

docker run --rm -it \
  --mount type=volume,source=codex-sdk-cli-home,target=/home/codex/.codex \
  codex-sdk-cli login device

docker run --rm \
  --mount type=volume,source=codex-sdk-cli-home,target=/home/codex/.codex \
  codex-sdk-cli account
```

Docker Compose를 쓰면 같은 named volume과 S3 bind mount 설정을 반복하지 않아도 된다.

```bash
mkdir -p .docker-empty-s3
docker compose build
docker compose run --rm codex login device
docker compose run --rm codex account
```

호스트의 S3 Mountpoint 경로를 컨테이너에 `/data/s3`로 전달하려면:

```bash
CODEX_CLI_S3_DIR=/mnt/s3/my-data-bucket \
  docker compose run --rm codex run --cwd /data/s3 "Summarize this directory."
```

## REST API 컨테이너

Compose의 `api` 서비스는 같은 이미지에서 `codex-api` entrypoint를 실행한다.

```bash
docker compose up api
```

기본 주소는 `http://localhost:8000`이고, OpenAPI UI는 `/docs`에서 확인한다.

```bash
curl -sS -X POST http://localhost:8000/codex/runs \
  -H 'content-type: application/json' \
  -d '{"prompt":"Describe /work in one sentence.","baseInstructions":"You are concise.","developerInstructions":"Answer in Korean."}'
```

## GitHub Actions 자동 배포

Terraform은 GitHub Actions가 AWS OIDC로 assume할 IAM role과 ECR repository를 만든다.
`main` branch push에서 CI가 성공하면 workflow가 다음 순서로 배포한다.

1. Docker image를 빌드하고 ECR에 `sha-<commit>`과 `latest` tag로 push한다.
2. SSM `AWS-RunShellScript`로 EC2에 배포 명령을 보낸다.
3. EC2가 ECR image를 pull하고 `codex-sdk-api` 컨테이너를 재기동한다.
4. EC2 내부에서 `http://127.0.0.1:8000/health`를 호출해 배포를 검증한다.

GitHub repository variables는 다음 값이 필요하다.

```text
AWS_REGION
AWS_ROLE_ARN
ECR_REPOSITORY
EC2_INSTANCE_ID
APP_PORT
CONTAINER_NAME
CODEX_CLI_SANDBOX
CODEX_CLI_APPROVAL
```

기본 Terraform 설정은 API port `8000`을 `0.0.0.0/0`에 공개한다. 공개 URL은
Terraform output의 `public_api_url`에서 확인한다.

```powershell
terraform -chdir=infra/aws-codex-cli output public_api_url
Invoke-RestMethod http://<public-ip>:8000/health
```

인터넷 공개 없이 확인하려면 `api_cidr_blocks=[]`로 적용하고 SSM port forwarding을 사용한다.

```powershell
aws ssm start-session `
  --target <instance-id> `
  --region ap-northeast-2 `
  --document-name AWS-StartPortForwardingSession `
  --parameters '{"portNumber":["8000"],"localPortNumber":["8000"]}'
```

별도 터미널에서:

```powershell
Invoke-RestMethod http://localhost:8000/health
```
