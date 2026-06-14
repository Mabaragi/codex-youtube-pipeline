from __future__ import annotations

from pathlib import Path

from codex_sdk_cli.api.s3_mount import _find_mount_entry, _is_s3_mount


def test_find_mount_entry_detects_mount_s3_target() -> None:
    mountinfo = (
        "31 23 0:29 / / rw,relatime - overlay overlay rw\n"
        "77 31 0:99 / /data/s3 rw,nosuid,nodev,relatime - "
        "fuse.mount-s3 mount-s3 rw,user_id=0,group_id=0\n"
    )

    entry = _find_mount_entry(Path("/data/s3"), mountinfo)

    assert entry is not None
    assert entry.mount_point == "/data/s3"
    assert entry.filesystem_type == "fuse.mount-s3"
    assert _is_s3_mount(entry) is True


def test_find_mount_entry_uses_deepest_parent_mount() -> None:
    mountinfo = (
        "31 23 0:29 / / rw,relatime - overlay overlay rw\n"
        "77 31 0:99 / /data/s3 rw,nosuid,nodev,relatime - "
        "fuse.mount-s3 mount-s3 rw,user_id=0,group_id=0\n"
        "78 31 0:42 / /data rw,relatime - xfs /dev/nvme0n1p1 rw\n"
    )

    entry = _find_mount_entry(Path("/data/s3/prefix/file.txt"), mountinfo)

    assert entry is not None
    assert entry.mount_point == "/data/s3"
    assert _is_s3_mount(entry) is True


def test_find_mount_entry_does_not_treat_regular_bind_mount_as_s3() -> None:
    mountinfo = (
        "31 23 0:29 / / rw,relatime - overlay overlay rw\n"
        "77 31 0:42 /opt/codex-sdk-cli/docker/empty-s3 /data/s3 rw,relatime - "
        "xfs /dev/nvme0n1p1 rw\n"
    )

    entry = _find_mount_entry(Path("/data/s3"), mountinfo)

    assert entry is not None
    assert entry.filesystem_type == "xfs"
    assert _is_s3_mount(entry) is False
