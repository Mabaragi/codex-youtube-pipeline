import Link from "next/link";
import { Filter, RotateCcw } from "lucide-react";
import type { ChangeEventHandler, ReactNode } from "react";
import type { OpsChannel } from "@/lib/types";

type SelectOption = {
  label: string;
  value: string;
};

export function FilterField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="grid gap-1 text-xs font-semibold text-slate-600">
      {label}
      {children}
    </label>
  );
}

export function ChannelFilterSelect({
  channels,
  value,
  onChange,
}: {
  channels: OpsChannel[];
  value: number | null | undefined;
  onChange?: ChangeEventHandler<HTMLSelectElement>;
}) {
  const selectedValue = value ? String(value) : "";
  const hasSelectedChannel = channels.some((channel) => channel.channelId === value);

  return (
    <FilterField label="Channel">
      <select
        className="ops-input"
        name="channelId"
        defaultValue={selectedValue}
        onChange={onChange}
      >
        <option value="">All channels</option>
        {value && !hasSelectedChannel ? <option value={value}>#{value}</option> : null}
        {channels.map((channel) => (
          <option key={channel.channelId} value={channel.channelId}>
            #{channel.channelId} {channel.name} ({channel.handle})
          </option>
        ))}
      </select>
    </FilterField>
  );
}

export function FilterInput({
  label,
  name,
  defaultValue,
  placeholder,
}: {
  label: string;
  name: string;
  defaultValue: number | string | null | undefined;
  placeholder?: string;
}) {
  return (
    <FilterField label={label}>
      <input
        className="ops-input"
        name={name}
        defaultValue={defaultValue ?? ""}
        placeholder={placeholder}
      />
    </FilterField>
  );
}

export function FilterSelect({
  label,
  name,
  defaultValue,
  options,
  onChange,
}: {
  label: string;
  name: string;
  defaultValue: string | null | undefined;
  options: SelectOption[];
  onChange?: ChangeEventHandler<HTMLSelectElement>;
}) {
  return (
    <FilterField label={label}>
      <select
        className="ops-input"
        name={name}
        defaultValue={defaultValue ?? ""}
        onChange={onChange}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </FilterField>
  );
}

export function FilterActions({ resetHref }: { resetHref: string }) {
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      <button className="ops-button ops-button-primary" type="submit">
        <Filter size={15} />
        Apply
      </button>
      <Link className="ops-button" href={resetHref}>
        <RotateCcw size={15} />
        Reset
      </Link>
    </div>
  );
}
