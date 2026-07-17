"use client";

import { createContext, type ReactNode, use, useMemo, useState } from "react";

type SelectionType = "selected" | "channel" | "filter" | "nextEligible";

export interface SelectionValue {
  type: SelectionType;
  videoIds: number[];
  channelId: number | null;
  search: string;
  limit: number;
}

interface SelectionContextValue {
  state: SelectionValue;
  actions: {
    setType: (value: SelectionType) => void;
    setVideoIds: (value: string) => void;
    setChannelId: (value: string) => void;
    setSearch: (value: string) => void;
    setLimit: (value: string) => void;
  };
  meta: { disabled: boolean; onChange?: (value: SelectionValue) => void };
}

const SelectionContext = createContext<SelectionContextValue | null>(null);

function useSelectionBuilder(): SelectionContextValue {
  const value = use(SelectionContext);
  if (!value) throw new Error("SelectionBuilder components require SelectionBuilder.Provider.");
  return value;
}

function Provider({ children, disabled = false, onChange }: { children: ReactNode; disabled?: boolean; onChange?: (value: SelectionValue) => void }) {
  const [state, setState] = useState<SelectionValue>({ type: "nextEligible", videoIds: [], channelId: null, search: "", limit: 20 });
  const value = useMemo<SelectionContextValue>(() => {
    const update = (next: SelectionValue) => {
      setState(next);
      onChange?.(next);
    };
    return {
      state,
      actions: {
        setType: (type) => update({ ...state, type }),
        setVideoIds: (raw) => update({ ...state, videoIds: raw.split(",").map((part) => Number(part.trim())).filter((id) => Number.isInteger(id) && id > 0) }),
        setChannelId: (raw) => update({ ...state, channelId: raw ? Number(raw) : null }),
        setSearch: (search) => update({ ...state, search }),
        setLimit: (raw) => update({ ...state, limit: Math.min(200, Math.max(1, Number(raw) || 1)) }),
      },
      meta: { disabled, onChange },
    };
  }, [disabled, onChange, state]);
  return <SelectionContext value={value}>{children}</SelectionContext>;
}

function Root({ children }: { children: ReactNode }) {
  return <fieldset data-slot="selection-builder" className="grid gap-3"><legend className="mb-1 text-sm font-semibold">대상 선택</legend>{children}</fieldset>;
}

function TypeField() {
  const { state, actions, meta } = useSelectionBuilder();
  return <label className="grid gap-1 text-xs font-medium" htmlFor="selection-type">선택 방식<select id="selection-type" name="selectionType" value={state.type} onChange={(event) => actions.setType(event.target.value as SelectionType)} disabled={meta.disabled} className="min-h-11 rounded-md border bg-[var(--surface)] px-3 text-sm"><option value="nextEligible">다음 처리 가능</option><option value="selected">영상 ID 직접 선택</option><option value="channel">채널</option><option value="filter">검색 필터</option></select></label>;
}

function CriteriaFields() {
  const { state, actions, meta } = useSelectionBuilder();
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {state.type === "selected" ? <label className="grid gap-1 text-xs font-medium" htmlFor="selection-video-ids">영상 ID 목록<input id="selection-video-ids" name="videoIds" inputMode="numeric" autoComplete="off" placeholder="151, 152, 153…" disabled={meta.disabled} onChange={(event) => actions.setVideoIds(event.target.value)} className="min-h-11 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" /></label> : null}
      {state.type === "channel" || state.type === "filter" ? <label className="grid gap-1 text-xs font-medium" htmlFor="selection-channel">채널 ID<input id="selection-channel" name="channelId" type="number" min={1} inputMode="numeric" autoComplete="off" disabled={meta.disabled} onChange={(event) => actions.setChannelId(event.target.value)} className="min-h-11 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" /></label> : null}
      {state.type === "filter" ? <label className="grid gap-1 text-xs font-medium" htmlFor="selection-search">검색어<input id="selection-search" name="search" autoComplete="off" placeholder="제목 또는 YouTube ID…" disabled={meta.disabled} value={state.search} onChange={(event) => actions.setSearch(event.target.value)} className="min-h-11 rounded-md border bg-[var(--surface)] px-3 text-sm" /></label> : null}
      {state.type !== "selected" ? <label className="grid gap-1 text-xs font-medium" htmlFor="selection-limit">최대 영상 수<input id="selection-limit" name="limit" type="number" min={1} max={200} inputMode="numeric" autoComplete="off" disabled={meta.disabled} value={state.limit} onChange={(event) => actions.setLimit(event.target.value)} className="min-h-11 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" /></label> : null}
    </div>
  );
}

export const SelectionBuilder = { Provider, Root, TypeField, CriteriaFields };
