from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_S3_MOUNT_PATH = Path("/data/s3")
MOUNTINFO_PATH = Path("/proc/self/mountinfo")


@dataclass(frozen=True, slots=True)
class MountEntry:
    mount_point: str
    filesystem_type: str
    source: str


@dataclass(frozen=True, slots=True)
class S3MountStatus:
    path: str
    exists: bool
    readable: bool
    is_mount: bool
    filesystem_type: str | None
    source: str | None
    s3_mounted: bool
    reason: str

    def to_api_dict(self) -> dict[str, object]:
        payload = asdict(self)
        return {
            "path": payload["path"],
            "exists": payload["exists"],
            "readable": payload["readable"],
            "isMount": payload["is_mount"],
            "filesystemType": payload["filesystem_type"],
            "source": payload["source"],
            "s3Mounted": payload["s3_mounted"],
            "reason": payload["reason"],
        }


def get_s3_mount_status(path: Path = DEFAULT_S3_MOUNT_PATH) -> S3MountStatus:
    mount_entry = _find_mount_entry(path, _read_mountinfo())
    exists = path.exists()
    readable = path.is_dir() and _can_read_directory(path)
    is_mount = path.is_mount() if exists else False
    s3_mounted = mount_entry is not None and _is_s3_mount(mount_entry)

    return S3MountStatus(
        path=path.as_posix(),
        exists=exists,
        readable=readable,
        is_mount=is_mount,
        filesystem_type=mount_entry.filesystem_type if mount_entry is not None else None,
        source=mount_entry.source if mount_entry is not None else None,
        s3_mounted=s3_mounted,
        reason=_reason(exists, is_mount, mount_entry, s3_mounted),
    )


def _read_mountinfo() -> str:
    try:
        return MOUNTINFO_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def _find_mount_entry(path: Path, mountinfo: str) -> MountEntry | None:
    target = path.as_posix()
    best_match: MountEntry | None = None

    for line in mountinfo.splitlines():
        entry = _parse_mountinfo_line(line)
        if entry is None:
            continue
        if (
            target == entry.mount_point
            or target.startswith(f"{entry.mount_point.rstrip('/')}/")
        ) and (best_match is None or len(entry.mount_point) > len(best_match.mount_point)):
            best_match = entry

    return best_match


def _parse_mountinfo_line(line: str) -> MountEntry | None:
    if " - " not in line:
        return None

    left, right = line.split(" - ", maxsplit=1)
    left_fields = left.split()
    right_fields = right.split()
    if len(left_fields) < 5 or len(right_fields) < 2:
        return None

    return MountEntry(
        mount_point=_decode_mountinfo_path(left_fields[4]),
        filesystem_type=right_fields[0],
        source=right_fields[1],
    )


def _decode_mountinfo_path(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _is_s3_mount(entry: MountEntry) -> bool:
    haystack = f"{entry.filesystem_type} {entry.source}".lower()
    return "mount-s3" in haystack


def _can_read_directory(path: Path) -> bool:
    try:
        next(path.iterdir(), None)
    except StopIteration:
        return True
    except OSError:
        return False
    return True


def _reason(
    exists: bool,
    is_mount: bool,
    mount_entry: MountEntry | None,
    s3_mounted: bool,
) -> str:
    if s3_mounted:
        return "s3_mount_detected"
    if not exists:
        return "path_missing"
    if mount_entry is None:
        return "mountinfo_entry_missing"
    if not is_mount:
        return "path_exists_but_is_not_mountpoint"
    return "mountpoint_is_not_mount_s3"
