"use client";

import type { ChangeEvent } from "react";
import type { PromptDetail } from "@/lib/types";

type PromptVersionSelectProps = {
  detail: PromptDetail | undefined;
  disabled?: boolean;
  label?: string;
  loading?: boolean;
  onChange: (versionId: number | null) => void;
  value: number | null;
};

export function PromptVersionSelect({
  detail,
  disabled = false,
  label = "Prompt",
  loading = false,
  onChange,
  value,
}: PromptVersionSelectProps) {
  const publishedVersions =
    detail?.versions.filter((version) => version.status === "PUBLISHED") ?? [];

  function handleChange(event: ChangeEvent<HTMLSelectElement>) {
    const nextValue = event.currentTarget.value;
    onChange(nextValue ? Number(nextValue) : null);
  }

  return (
    <label className="grid gap-1 text-xs font-medium text-slate-600">
      {label}
      <select
        className="ops-input"
        disabled={disabled || loading}
        onChange={handleChange}
        value={value?.toString() ?? ""}
      >
        <option value="">{loading ? "Loading prompts..." : "Active prompt"}</option>
        {publishedVersions.map((version) => (
          <option key={version.id} value={version.id}>
            {version.versionLabel}
            {version.isActive ? " (active)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
