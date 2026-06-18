"use client";

import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { useOpsSummary } from "@/lib/queries";
import { formatDateTime } from "@/lib/format";

export function OverviewPage() {
  const { data, isLoading, error } = useOpsSummary();

  return (
    <>
      <PageHeader title="Overview" />
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      {data ? (
        <div className="grid gap-4">
          <section className="ops-panel p-4">
            <div className="grid gap-4 md:grid-cols-4">
              <Metric label="API" value={data.apiStatus} status="ok" />
              <Metric
                label="S3 mounted"
                value={String(data.s3.s3Mounted ?? "unknown")}
                status={data.s3.s3Mounted ? "ok" : "none"}
              />
              <Metric label="Channels" value={String(data.counts.channels)} />
              <Metric label="Videos" value={String(data.counts.videos)} />
            </div>
          </section>
          <section className="grid gap-4 lg:grid-cols-2">
            <div className="ops-panel p-4">
              <h2 className="mb-3 text-sm font-semibold">Task Status</h2>
              <StatusList items={data.counts.videoTasks} />
            </div>
            <div className="ops-panel p-4">
              <h2 className="mb-3 text-sm font-semibold">Pipeline Status</h2>
              <StatusList items={data.counts.pipelineJobs} />
            </div>
          </section>
          <section className="ops-panel p-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <AlertTriangle size={16} />
              Recent Failures
            </h2>
            <div className="grid gap-2">
              {data.recentFailures.length === 0 ? (
                <div className="text-sm text-slate-500">No recent failures.</div>
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
          </section>
        </div>
      ) : null}
    </>
  );
}

function Metric({
  label,
  value,
  status,
}: {
  label: string;
  value: string;
  status?: string;
}) {
  return (
    <div className="border-l-2 border-slate-200 pl-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 flex items-center gap-2 text-xl font-semibold">
        {status === "ok" ? <CheckCircle2 size={18} color="var(--success)" /> : null}
        {value}
      </div>
    </div>
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
