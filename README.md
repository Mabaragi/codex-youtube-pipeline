# Codex SDK CLI Demo

A small Python CLI that uses the OpenAI Codex SDK to start or resume Codex
threads, run prompts, and manage local Codex authentication.

## Install

```powershell
uv sync --dev
```

## Login

```powershell
uv run codex-demo login browser
uv run codex-demo login device
uv run codex-demo login api-key
```

`login api-key` reads `--api-key` when provided, then `CODEX_CLI_API_KEY`, then
falls back to a hidden prompt.

## Run Codex

Start a new ephemeral thread:

```powershell
uv run codex-demo run "Describe this repository in one sentence."
```

Persist a new thread when you want to resume it later:

```powershell
uv run codex-demo run --persist "Describe this repository in one sentence."
```

Resume a previous thread:

```powershell
uv run codex-demo run --thread-id <thread-id> "Continue from the previous answer."
```

By default, newly created threads are ephemeral and should not be materialized on
disk by the Codex SDK. Use `--persist` only for threads that need a durable
thread id for later `--thread-id` resume. `--persist` has no effect when
resuming an existing thread.

Useful options:

```powershell
uv run codex-demo run --sandbox read-only --approval deny-all "Review the project."
uv run codex-demo run --cwd C:\path\to\repo --model gpt-5.4 "Explain this codebase."
uv run codex-demo run --empty-base-instructions "Answer with no SDK base instructions."
uv run codex-demo run --empty-developer-instructions "Answer with no SDK developer instructions."
```

`--empty-base-instructions` and `--empty-developer-instructions` send blank
instruction overrides to the Codex SDK. The SDK server rejects an actual empty
string during turn execution, so the CLI uses whitespace overrides to compare
behavior or token usage without the SDK's default instructions.

## Account

```powershell
uv run codex-demo account
uv run codex-demo logout
```

## Configuration

Environment variables use the `CODEX_CLI_` prefix:

- `CODEX_CLI_MODEL`
- `CODEX_CLI_SANDBOX` (`read-only`, `workspace-write`, `full-access`)
- `CODEX_CLI_APPROVAL` (`auto-review`, `deny-all`)
- `CODEX_CLI_CODEX_BIN`
- `CODEX_CLI_API_KEY`
- `CODEX_CLI_YOUTUBE_HTTP_PROXY`
- `CODEX_CLI_YOUTUBE_HTTPS_PROXY`

## Checks

```powershell
uv run pytest
uv run ruff check .
uv run pyrefly check --min-severity warn
```

## AWS Deployment

Build the wheel, validate Terraform, and create a plan:

```powershell
.\scripts\deploy_aws.ps1
```

Apply the AWS EC2 deployment:

```powershell
.\scripts\deploy_aws.ps1 -Apply
```

See `docs/AWS_DEPLOYMENT.md` for SSM login, Codex authentication, and optional
S3 Mountpoint usage.

## Docker

Build and run the CLI image locally:

```powershell
docker build -t codex-sdk-cli .
docker run --rm codex-sdk-cli --help
```

When S3 is mounted on the host, pass it into the container with a bind mount:

```bash
docker run --rm \
  --mount type=bind,source=/mnt/s3,target=/data/s3,readonly \
  codex-sdk-cli \
  run --sandbox read-only "Read /data/s3/prompt.md and summarize it."
```

Codex login state and API keys are not baked into the image. Pass credentials at
runtime with environment variables or a mounted state directory.

To keep Codex login state across disposable containers, mount a persistent
volume at the Codex user's state directory:

```powershell
docker volume create codex-sdk-cli-home
docker run --rm -it `
  --mount type=volume,source=codex-sdk-cli-home,target=/home/codex/.codex `
  codex-sdk-cli login device
docker run --rm `
  --mount type=volume,source=codex-sdk-cli-home,target=/home/codex/.codex `
  codex-sdk-cli account
```

Docker Compose keeps the same state volume without repeating the mount flags:

```powershell
New-Item -ItemType Directory -Force .docker-empty-s3 | Out-Null
docker compose build
docker compose run --rm codex login device
docker compose run --rm codex account
docker compose run --rm codex run --sandbox read-only "Describe /work in one sentence."
```

To expose a host S3 mount to the container, set `CODEX_CLI_S3_DIR`:

```powershell
$env:CODEX_CLI_S3_DIR = "C:\path\to\mounted\s3"
docker compose run --rm codex run --cwd /data/s3 "Summarize this directory."
```

## REST API

Run the FastAPI wrapper:

```powershell
docker compose up api
```

Open `http://localhost:8000/docs`, or call the API directly:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/codex/runs `
  -ContentType "application/json" `
  -Body '{"prompt":"Describe /work in one sentence.","baseInstructions":"You are concise.","developerInstructions":"Answer in Korean."}'
```

Fetch YouTube captions by URL or video ID:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/youtube/transcripts `
  -ContentType "application/json" `
  -Body '{"video":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","languages":["ko","en"],"preserveFormatting":false}'
```

The YouTube endpoint returns the selected transcript metadata, newline-joined
plain text, and the original timed caption segments. If YouTube blocks cloud
provider traffic, configure `CODEX_CLI_YOUTUBE_HTTP_PROXY` and/or
`CODEX_CLI_YOUTUBE_HTTPS_PROXY` before starting the API.

For GitHub Actions EC2 deploys, store proxy URLs as repository secrets named
`CODEX_CLI_YOUTUBE_HTTP_PROXY` and `CODEX_CLI_YOUTUBE_HTTPS_PROXY`. Repository
variables with the same names also work for non-sensitive proxy URLs, but
authenticated proxy URLs should be secrets.

The REST API keeps route handlers thin: HTTP DTOs live in the Codex domain,
application workflows live in use cases, and the actual Codex SDK adapter lives
under the infrastructure layer.

## GitHub CI/CD

GitHub Actions runs Python quality gates and a Docker build on pull requests and
`main` pushes. Pushes to `main` or `v*.*.*` tags also publish the Docker image to
GitHub Container Registry:

```text
ghcr.io/<owner>/<repo>:latest
ghcr.io/<owner>/<repo>:sha-<commit>
ghcr.io/<owner>/<repo>:vX.Y.Z
```

On `main` pushes, CI also deploys the FastAPI container to the Terraform-managed
EC2 host through AWS OIDC, ECR, and SSM after quality gates pass. The default
Terraform settings expose port `8000` publicly through the instance security
group.

Set the optional GitHub repository variable `S3_MOUNT_BUCKET` to mount that
bucket on the EC2 host with Mountpoint for Amazon S3 and bind it into the API
container at `/data/s3`. Set `S3_MOUNT_PREFIX` to restrict the mount to a
bucket prefix. Set `S3_MOUNT_TEST_FILE` to a file path inside the mounted prefix
when the deploy should prove that the container can read a known S3 object.
The deploy job verifies the host mount source, calls `/health/s3`, and reads the
optional test file from inside the container. Container mountinfo may report the
bind-mounted filesystem rather than the host's Mountpoint source. On EC2, the
Mountpoint process is managed by `codex-sdk-s3-mount.service` so the mount
survives beyond the one-shot SSM deployment command.
