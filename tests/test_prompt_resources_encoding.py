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


def test_micro_event_prompt_requires_plain_declarative_event_style() -> None:
    text = (PROMPT_RESOURCE_DIR / "micro_event_extract_v3.md").read_text(
        encoding="utf-8"
    )

    assert "공손체 `~습니다`나 해요체 `~해요`가 아니라 해라체/평서형 `~다`" in text


def test_timeline_prompt_guides_display_summary_feed_caption_tone() -> None:
    text = (PROMPT_RESOURCE_DIR / "timeline_compose_v3.md").read_text(
        encoding="utf-8"
    )

    assert "좋은 클립 목록 캡션처럼" in text
    assert "실제로 볼 장면 2~3개를 짧게 압축" in text
    assert "보고서형 종결과 문장 구조를 피한다" in text
    assert "특정 어미나 종결 패턴을 정답처럼 반복하지 않는다" in text
    assert "가볍고 귀엽고 장면감 있게" in text
    assert "`처음부터 끝까지`, `X에서 Y까지`, `X하다가 Y까지`, `X 뒤에 Y`" not in text
    assert "`~한다.`, `~했다.`, `~된다.`, `~이다.`로 끝나는 설명문보다" not in text
    assert "해라체/평서형 `~다` 문장" not in text
