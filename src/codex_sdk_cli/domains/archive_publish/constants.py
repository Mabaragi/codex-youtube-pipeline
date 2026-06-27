from __future__ import annotations

ARCHIVE_PUBLISH_TASK_NAME = "archive_publish"
ARCHIVE_PUBLISH_TASK_VERSION = "v1"
ARCHIVE_PUBLISH_RUNNER_ID = "archive-publish-api"
ARCHIVE_PUBLISH_BATCH_SCAN_LIMIT = 500

ARCHIVE_POINTER_CACHE_CONTROL = "public, max-age=60"
ARCHIVE_IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
