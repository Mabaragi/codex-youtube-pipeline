# Segment classification sample

공개 저장소용 샘플 fallback이다. 운영 프롬프트는 DB `prompt_versions` 또는 private prompt pack으로
관리한다. 반드시 JSON object만 출력한다.

Return structured segments over the supplied episode indices. Cover every episode exactly
once in order. Activities are chat, game, sing, watch, cafe, setup, asmr, other. Collaboration
is a separate boolean with participant names. Use input evidence, and preserve solo intervals.
Set phase to opening, main, or closing; opening and closing can occur only at broadcast edges.
For unavailable optional descriptions or names use null or an empty list as required by the
output schema. This is a public sample; publish the approved taxonomy prompt in the prompt
registry before production use.
