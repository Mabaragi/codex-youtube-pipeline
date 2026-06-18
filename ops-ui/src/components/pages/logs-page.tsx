"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Eye, Filter, RotateCcw } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { formatDateTime, compactId } from "@/lib/format";
import { eventSubjectLabel, logsHref } from "@/lib/logs";
import { useOperationEvents } from "@/lib/queries";
import type { OperationEvent, OperationEventFilters } from "@/lib/types";

type LogsPageProps = {
  initialFilters: OperationEventFilters;
};

export function LogsPage({ initialFilters }: LogsPageProps) {
  const router = useRouter();
  const { data, isLoading, error } = useOperationEvents(initialFilters);
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const selectedEvent =
    data?.items.find((event) => event.eventId === selectedEventId) ??
    data?.items[0] ??
    null;

  const columns = useMemo<ColumnDef<OperationEvent>[]>(
    () => [
      {
        id: "time",
        header: "Time",
        cell: ({ row }) => (
          <span className="whitespace-nowrap">{formatDateTime(row.original.occurredAt)}</span>
        ),
      },
      {
        id: "severity",
        header: "Severity",
        cell: ({ row }) => <StatusBadge status={row.original.severity} />,
      },
      {
        id: "event",
        header: "Event",
        cell: ({ row }) => (
          <div className="max-w-[220px] truncate font-semibold">
            {row.original.eventType}
          </div>
        ),
      },
      {
        id: "subject",
        header: "Subject",
        cell: ({ row }) => (
          <div>
            <div>{eventSubjectLabel(row.original)}</div>
            <div className="text-xs text-slate-500">
              {compactId(row.original.externalKey)}
            </div>
          </div>
        ),
      },
      {
        id: "job-task",
        header: "Job/task",
        cell: ({ row }) => <JobTaskCell event={row.original} />,
      },
      {
        id: "message",
        header: "Message",
        cell: ({ row }) => (
          <div className="max-w-[420px] text-slate-700">{row.original.message}</div>
        ),
      },
      {
        id: "details",
        header: "",
        cell: ({ row }) => (
          <button
            className="ops-button"
            type="button"
            onClick={() => setSelectedEventId(row.original.eventId)}
          >
            <Eye size={15} />
            Details
          </button>
        ),
      },
    ],
    [],
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    router.push(logsHref(formFilters(form)));
  }

  return (
    <>
      <PageHeader title="Operation Logs" />
      <form
        key={JSON.stringify(initialFilters)}
        className="ops-panel mb-4 p-4"
        onSubmit={handleSubmit}
      >
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
          <FilterSelect defaultValue={initialFilters.severity ?? ""} />
          <FilterInput label="Event" name="eventType" defaultValue={initialFilters.eventType} />
          <FilterInput
            label="Subject type"
            name="subjectType"
            defaultValue={initialFilters.subjectType}
          />
          <FilterInput
            label="Subject ID"
            name="subjectId"
            defaultValue={initialFilters.subjectId}
          />
          <FilterInput label="Job ID" name="jobId" defaultValue={initialFilters.jobId} />
          <FilterInput
            label="Task ID"
            name="videoTaskId"
            defaultValue={initialFilters.videoTaskId}
          />
          <FilterInput
            label="Channel ID"
            name="channelId"
            defaultValue={initialFilters.channelId}
          />
          <FilterInput label="Video ID" name="videoId" defaultValue={initialFilters.videoId} />
          <FilterInput label="Limit" name="limit" defaultValue={initialFilters.limit ?? 50} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="ops-button ops-button-primary" type="submit">
            <Filter size={15} />
            Apply
          </button>
          <Link className="ops-button" href="/logs">
            <RotateCcw size={15} />
            Reset
          </Link>
        </div>
      </form>

      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0">
          <DataTable columns={columns} data={data?.items ?? []} />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {data?.nextCursor ? (
              <Link
                className="ops-button"
                href={logsHref({ ...initialFilters, cursor: data.nextCursor })}
              >
                Older
              </Link>
            ) : null}
            {initialFilters.cursor ? (
              <Link
                className="ops-button"
                href={logsHref({ ...initialFilters, cursor: null })}
              >
                Newest
              </Link>
            ) : null}
          </div>
        </div>
        <EventDetail event={selectedEvent} />
      </div>
    </>
  );
}

function FilterSelect({ defaultValue }: { defaultValue: string }) {
  return (
    <label className="grid gap-1 text-xs font-semibold text-slate-600">
      Severity
      <select className="ops-input" name="severity" defaultValue={defaultValue}>
        <option value="">All</option>
        <option value="info">info</option>
        <option value="warning">warning</option>
        <option value="error">error</option>
      </select>
    </label>
  );
}

function FilterInput({
  label,
  name,
  defaultValue,
}: {
  label: string;
  name: string;
  defaultValue: number | string | null | undefined;
}) {
  return (
    <label className="grid gap-1 text-xs font-semibold text-slate-600">
      {label}
      <input className="ops-input" name={name} defaultValue={defaultValue ?? ""} />
    </label>
  );
}

function JobTaskCell({ event }: { event: OperationEvent }) {
  return (
    <div className="grid gap-1 text-xs text-slate-600">
      <span>{event.jobId ? `job #${event.jobId}` : "job -"}</span>
      <span>{event.jobAttemptId ? `attempt #${event.jobAttemptId}` : "attempt -"}</span>
      <span>{event.videoTaskId ? `task #${event.videoTaskId}` : "task -"}</span>
    </div>
  );
}

function EventDetail({ event }: { event: OperationEvent | null }) {
  if (!event) {
    return (
      <aside className="ops-panel p-4 text-sm text-slate-500">
        Select an event.
      </aside>
    );
  }

  return (
    <aside className="ops-panel p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Event Detail</h2>
        <StatusBadge status={event.severity} />
      </div>
      <div className="grid gap-2 border-t border-slate-200 py-3 text-sm">
        <DetailRow label="Event" value={event.eventType} />
        <DetailRow label="Actor" value={event.actorType} />
        <DetailRow label="Source" value={event.source} />
        <DetailRow label="Subject" value={eventSubjectLabel(event)} />
        <DetailRow label="Job" value={event.jobId ? `#${event.jobId}` : "-"} />
        <DetailRow label="Attempt" value={event.jobAttemptId ? `#${event.jobAttemptId}` : "-"} />
        <DetailRow label="Task" value={event.videoTaskId ? `#${event.videoTaskId}` : "-"} />
        <DetailRow label="Channel" value={event.channelId ? `#${event.channelId}` : "-"} />
        <DetailRow label="Video" value={event.videoId ? `#${event.videoId}` : "-"} />
        <DetailRow label="External call" value={event.externalApiCallId ? `#${event.externalApiCallId}` : "-"} />
        <DetailRow label="Error" value={event.errorType ?? "-"} />
      </div>
      {event.errorMessage ? (
        <div className="border-t border-slate-200 py-3 text-sm text-red-700">
          {event.errorMessage}
        </div>
      ) : null}
      <pre className="max-h-[360px] overflow-auto rounded border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
        {JSON.stringify(event.metadata, null, 2)}
      </pre>
    </aside>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[100px_minmax(0,1fr)] gap-2">
      <span className="text-xs font-semibold text-slate-500">{label}</span>
      <span className="min-w-0 break-words">{value}</span>
    </div>
  );
}

function formFilters(form: FormData): Partial<OperationEventFilters> {
  return {
    severity: severityValue(form.get("severity")),
    eventType: stringValue(form.get("eventType")),
    subjectType: stringValue(form.get("subjectType")),
    subjectId: numberValue(form.get("subjectId")),
    jobId: numberValue(form.get("jobId")),
    videoTaskId: numberValue(form.get("videoTaskId")),
    channelId: numberValue(form.get("channelId")),
    videoId: numberValue(form.get("videoId")),
    limit: numberValue(form.get("limit")) ?? 50,
  };
}

function stringValue(value: FormDataEntryValue | null): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

function numberValue(value: FormDataEntryValue | null): number | undefined {
  const text = stringValue(value);
  if (!text) {
    return undefined;
  }
  const parsed = Number(text);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

function severityValue(
  value: FormDataEntryValue | null,
): OperationEventFilters["severity"] | undefined {
  const text = stringValue(value);
  return text === "info" || text === "warning" || text === "error" ? text : undefined;
}
