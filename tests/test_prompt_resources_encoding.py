from __future__ import annotations

from pathlib import Path

PROMPT_RESOURCE_DIR = Path("src/codex_sdk_cli/domains/prompts/resources")
MOJIBAKE_MARKERS = (
    "\ufffd",
    "?묒",
    "?꾨",
    "?덈",
    "濡",
    "遺",
    "援",
    "釉",
    "筌",
    "獄",
    "揶",
    "餓",
)
EXPECTED_KOREAN_MARKERS = ("역할", "작업", "출력", "반드시")


def test_prompt_resources_are_clean_utf8_text() -> None:
    for path in PROMPT_RESOURCE_DIR.glob("*.md"):
        raw = path.read_bytes()
        text = raw.decode("utf-8")

        assert raw == text.encode("utf-8")
        assert any(marker in text for marker in EXPECTED_KOREAN_MARKERS), path
        for marker in MOJIBAKE_MARKERS:
            assert marker not in text, f"{path} contains mojibake marker {marker!r}"


def test_prompt_resources_are_public_safe_sample_fallbacks() -> None:
    for path in PROMPT_RESOURCE_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")

        assert "공개 저장소용 샘플 fallback" in text
        assert "DB `prompt_versions` 또는 private prompt pack" in text
        assert "반드시 JSON object만 출력한다" in text
