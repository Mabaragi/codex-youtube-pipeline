FROM python:3.13-slim AS builder

ENV UV_SYSTEM_PYTHON=1

WORKDIR /build

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md uv.lock ./
COPY src ./src

RUN uv build --wheel

FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1
ENV HOME=/home/codex

WORKDIR /work

RUN adduser --disabled-password --gecos "" codex \
    && mkdir -p /home/codex/.codex \
    && mkdir -p /data/db \
    && chown -R codex:codex /home/codex/.codex /data/db

COPY --from=builder /build/dist/*.whl /tmp/

RUN pip install --no-cache-dir /tmp/*.whl \
    && rm -f /tmp/*.whl

USER codex

ENTRYPOINT ["codex-demo"]
CMD ["--help"]
