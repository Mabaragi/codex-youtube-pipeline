from __future__ import annotations

import re
from dataclasses import dataclass

_HANGUL_BASE = 0xAC00
_HANGUL_END = 0xD7A3
_JONGSEONG_COUNT = 28
_JONGSEONG_BIEUP = 17
_JONGSEONG_NIEUN = 4

_PUNCTUATION = r"(?P<punct>[.!?])"
_FIXED_ENDING_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("이었습니다", "이었다"),
    ("였습니다", "였다"),
    ("하였습니다", "하였다"),
    ("했습니다", "했다"),
    ("되었습니다", "되었다"),
    ("됐습니다", "됐다"),
    ("입니다", "이다"),
    ("있습니다", "있다"),
    ("없습니다", "없다"),
    ("같습니다", "같다"),
    ("않습니다", "않다"),
    ("좋습니다", "좋다"),
    ("싫습니다", "싫다"),
    ("많습니다", "많다"),
    ("작습니다", "작다"),
    ("높습니다", "높다"),
    ("낮습니다", "낮다"),
    ("넓습니다", "넓다"),
    ("짧습니다", "짧다"),
    ("쉽습니다", "쉽다"),
    ("어렵습니다", "어렵다"),
    ("가득합니다", "가득하다"),
    ("빠릅니다", "빠르다"),
    ("다릅니다", "다르다"),
    ("힘듭니다", "힘들다"),
    ("큽니다", "크다"),
)
_FIXED_ENDING_PATTERNS = tuple(
    (re.compile(f"{re.escape(source)}{_PUNCTUATION}"), replacement)
    for source, replacement in _FIXED_ENDING_REPLACEMENTS
)
_SEUPNIDA_RE = re.compile(r"(?P<stem>[가-힣]+)습니다" + _PUNCTUATION)
_BIEUP_NIDA_RE = re.compile(r"(?P<syllable>[가-힣])니다" + _PUNCTUATION)


@dataclass(frozen=True, slots=True)
class TimelineStyleTextNormalization:
    text: str
    changed: bool
    unresolved_endings: list[str]


def normalize_timeline_style_text(text: str) -> TimelineStyleTextNormalization:
    """Normalize Korean polite timeline narration to plain declarative style."""

    normalized = text
    for pattern, replacement in _FIXED_ENDING_PATTERNS:
        normalized = pattern.sub(rf"{replacement}\g<punct>", normalized)
    normalized = _SEUPNIDA_RE.sub(_replace_seupnida, normalized)
    normalized = _BIEUP_NIDA_RE.sub(_replace_bieup_nida, normalized)
    return TimelineStyleTextNormalization(
        text=normalized,
        changed=normalized != text,
        unresolved_endings=polite_timeline_style_endings(normalized),
    )


def normalize_timeline_style_value(text: str) -> str:
    return normalize_timeline_style_text(text).text


def polite_timeline_style_endings(text: str) -> list[str]:
    endings = [match.group(0) for match in _SEUPNIDA_RE.finditer(text)]
    endings.extend(
        match.group(0)
        for match in _BIEUP_NIDA_RE.finditer(text)
        if _jongseong_index(match.group("syllable")) == _JONGSEONG_BIEUP
    )
    return endings


def _replace_seupnida(match: re.Match[str]) -> str:
    return f"{match.group('stem')}는다{match.group('punct')}"


def _replace_bieup_nida(match: re.Match[str]) -> str:
    syllable = match.group("syllable")
    if _jongseong_index(syllable) != _JONGSEONG_BIEUP:
        return match.group(0)
    return f"{_replace_jongseong(syllable, _JONGSEONG_NIEUN)}다{match.group('punct')}"


def _jongseong_index(syllable: str) -> int | None:
    code = ord(syllable)
    if code < _HANGUL_BASE or code > _HANGUL_END:
        return None
    return (code - _HANGUL_BASE) % _JONGSEONG_COUNT


def _replace_jongseong(syllable: str, jongseong_index: int) -> str:
    code = ord(syllable)
    offset = code - _HANGUL_BASE
    return chr(_HANGUL_BASE + offset - (offset % _JONGSEONG_COUNT) + jongseong_index)
