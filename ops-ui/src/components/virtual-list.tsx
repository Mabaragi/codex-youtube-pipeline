"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { type ReactNode, useRef } from "react";

export function VirtualList<T>({ items, estimateSize = 56, renderItem, label }: { items: T[]; estimateSize?: number; renderItem: (item: T, index: number) => ReactNode; label: string }) {
  const parentRef = useRef<HTMLDivElement>(null);
  // TanStack Virtual intentionally returns an imperative virtualizer model.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({ count: items.length, getScrollElement: () => parentRef.current, estimateSize: () => estimateSize, overscan: 8 });
  if (items.length <= 50) return <div role="list" aria-label={label} className="divide-y">{items.map((item, index) => <div role="listitem" key={index}>{renderItem(item, index)}</div>)}</div>;
  return <div ref={parentRef} role="list" aria-label={label} className="ops-scrollbar max-h-[38rem] overflow-auto contain-strict"><div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>{virtualizer.getVirtualItems().map((row) => <div role="listitem" key={row.key} className="absolute top-0 left-0 w-full border-b" style={{ transform: `translateY(${row.start}px)`, height: row.size }}>{renderItem(items[row.index], row.index)}</div>)}</div></div>;
}
