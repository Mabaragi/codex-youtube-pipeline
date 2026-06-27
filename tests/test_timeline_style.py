from __future__ import annotations

from codex_sdk_cli.domains.timelines.style import (
    normalize_timeline_style_value,
    polite_timeline_style_endings,
)


def test_timeline_style_normalizes_common_polite_endings() -> None:
    cases = {
        "\ud480\uc5b4\ub193\uc2b5\ub2c8\ub2e4.": "\ud480\uc5b4\ub193\ub294\ub2e4.",
        "\uc774\uc5b4\uc9d1\ub2c8\ub2e4.": "\uc774\uc5b4\uc9c4\ub2e4.",
        "\uc2dc\uc791\ud569\ub2c8\ub2e4.": "\uc2dc\uc791\ud55c\ub2e4.",
        "\uc788\uc2b5\ub2c8\ub2e4.": "\uc788\ub2e4.",
        "\uc5c6\uc2b5\ub2c8\ub2e4.": "\uc5c6\ub2e4.",
    }

    for source, expected in cases.items():
        assert normalize_timeline_style_value(source) == expected
        assert polite_timeline_style_endings(expected) == []


def test_timeline_style_normalizes_multiple_sentences() -> None:
    source = (
        "\uac8c\uc784\uc774 \uc774\uc5b4\uc9d1\ub2c8\ub2e4. "
        "\ub300\ud654\ub97c \ub098\ub215\ub2c8\ub2e4."
    )

    normalized = normalize_timeline_style_value(source)

    assert normalized == (
        "\uac8c\uc784\uc774 \uc774\uc5b4\uc9c4\ub2e4. \ub300\ud654\ub97c \ub098\ub208\ub2e4."
    )
    assert polite_timeline_style_endings(normalized) == []


def test_timeline_style_normalizes_fixed_adjective_endings() -> None:
    source = (
        "\uad6c\uac04\uc785\ub2c8\ub2e4. "
        "\uac00\ub4dd\ud569\ub2c8\ub2e4. "
        "\uc27d\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4. "
        "\uc18d\ub3c4\uac00 \ube60\ub985\ub2c8\ub2e4."
    )

    normalized = normalize_timeline_style_value(source)

    assert normalized == (
        "\uad6c\uac04\uc774\ub2e4. "
        "\uac00\ub4dd\ud558\ub2e4. "
        "\uc27d\uc9c0 \uc54a\ub2e4. "
        "\uc18d\ub3c4\uac00 \ube60\ub974\ub2e4."
    )
    assert polite_timeline_style_endings(normalized) == []
