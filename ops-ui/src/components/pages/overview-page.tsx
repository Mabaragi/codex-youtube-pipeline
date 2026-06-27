"use client";

import Link from "next/link";
import { ScrollText } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import {
  ActionPanel,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricStrip,
} from "@/components/ui-primitives";
import { useOperationEvents, useOpsSummary } from "@/lib/queries";
import { compactId, formatDateTime } from "@/lib/format";
import { eventLogLinkFilters, eventSubjectLabel, logsHref } from "@/lib/logs";

export function OverviewPage() {
  const { data, isLoading, error } = useOpsSummary();
  const recentEvents = useOperationEvents({ limit: 10 });

  return (
    <>
      <PageHeader
        title="Overview"
        description="API health, storage readiness, inventory counts, and the latest operational events."
      />
      {isLoading ? <LoadingState /> : null}
      {error ? <ErrorState message={String(error)} /> : null}
      {data ? (
        <div className="grid gap-4">
          <MetricStrip
            ariaLabel="Ops summary"
            items={[
              { label: "API", value: data.apiStatus, status: "ok" },
              {
                label: "S3 mounted",
                value: String(data.s3.s3Mounted ?? "unknown"),
                status: data.s3.s3Mounted ? "ok" : "none",
              },
              { label: "Channels", value: data.counts.channels },
              { label: "Videos", value: data.counts.videos },
            ]}
          />
          <section className="grid gap-4 lg:grid-cols-2">
            <section className="ops-panel p-4">
              <h2 className="mb-3 text-sm font-semibold">Task Status</h2>
              <StatusList items={data.counts.videoTasks} />
            </section>
            <section className="ops-panel p-4">
              <h2 className="mb-3 text-sm font-semibold">Pipeline Status</h2>
              <StatusList items={data.counts.pipelineJobs} />
            </section>
          </section>
          <ActionPanel
            title="Recent Failures"
            description="Failed jobs and tasks that need operator attention."
          >
            <div className="grid gap-2">
              {data.recentFailures.length === 0 ? (
                <EmptyState label="No recent failures." />
              ) : (
                data.recentFailures.map((failure) => (
                  <div
                    key={`${failure.kind}-${failure.id}`}
                    className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 py-2 text-sm"
                  >
                    <div>
                      <div className="font-semibold">{failure.label}</div>
                      <div className="text-slate-500">
                        {failure.errorType ?? failure.kind}
                        {failure.errorMessage ? `: ${failure.errorMessage}` : ""}
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <StatusBadge status={failure.status} />
                      <span className="text-xs text-slate-500">
                        {formatDateTime(failure.updatedAt)}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </ActionPanel>
          <ActionPanel
            title="Recent Events"
            description="Latest operation timeline entries across jobs, tasks, channels, and videos."
            actions={
              <Link className="ops-button" href="/logs">
                <ScrollText aria-hidden="true" size={15} />
                Logs
              </Link>
            }
          >
            <div className="grid gap-2">
              {recentEvents.isLoading ? (
                <EmptyState label="Loading…" />
              ) : null}
              {recentEvents.error ? (
                <div className="text-sm text-red-700">{String(recentEvents.error)}</div>
              ) : null}
              {recentEvents.data?.items.length === 0 ? (
                <EmptyState label="No rows." />
              ) : (
                recentEvents.data?.items.map((event) => (
                  <Link
                    key={event.eventId}
                    className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 py-2 text-sm hover:bg-slate-50"
                    href={logsHref(eventLogLinkFilters(event))}
                  >
                    <div className="min-w-0">
                      <div className="truncate font-semibold">{event.eventType}</div>
                      <div className="text-xs text-slate-500">
                        {eventSubjectLabel(event)}
                        {event.externalKey ? ` - ${compactId(event.externalKey)}` : ""}
                      </div>
                      <div className="mt-1 max-w-[680px] text-slate-600">
                        {event.message}
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <StatusBadge status={event.severity} />
                      <span className="text-xs text-slate-500">
                        {formatDateTime(event.occurredAt)}
                      </span>
                    </div>
                  </Link>
                ))
              )}
            </div>
          </ActionPanel>
        </div>
      ) : null}
    </>
  );
}

function StatusList({ items }: { items: { status: string; count: number }[] }) {
  return (
    <div className="flex flex-wrap gap-2">
      {items.length === 0 ? (
        <span className="text-sm text-slate-500">No rows.</span>
      ) : (
        items.map((item) => (
          <span key={item.status} className="flex items-center gap-2">
            <StatusBadge status={item.status} />
            <span className="text-sm font-semibold">{item.count}</span>
          </span>
        ))
      )}
    </div>
  );
}
