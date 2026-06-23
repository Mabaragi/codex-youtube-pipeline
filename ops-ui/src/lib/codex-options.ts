export const DEFAULT_CODEX_MODEL = "gpt-5.5";
export const DEFAULT_CODEX_REASONING_EFFORT = "medium";

export const CODEX_MODEL_OPTIONS = [
  { value: "gpt-5.5", label: "GPT-5.5" },
  { value: "gpt-5.4", label: "GPT-5.4" },
  { value: "gpt-5.4-mini", label: "GPT-5.4 Mini" },
] as const;

export const CODEX_REASONING_EFFORT_OPTIONS = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "XHigh" },
] as const;

export type CodexModelOption = (typeof CODEX_MODEL_OPTIONS)[number]["value"];
export type CodexReasoningEffortOption =
  (typeof CODEX_REASONING_EFFORT_OPTIONS)[number]["value"];
