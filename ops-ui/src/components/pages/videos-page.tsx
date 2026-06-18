"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Eye } from "lucide-react";
import type { FormEvent } from "react";
import { DataTable } from "@/components/data-table";
import {
  ChannelFilterSelect,
  FilterActions,
  FilterInput,
  FilterSelect,
} from "@/components/filter-controls";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { useOpsChannels, useOpsVideos } from "@/lib/queries";
import { compactId, formatDateTime } from "@/lib/format";
import type { OpsVideo, OpsVideoFilters } from "@/lib/types";
import {
  hrefWithQuery,
  positiveNumberFormValue,
  stringFormValue,
} from "@/lib/url-filters";

type VideosPageProps = {
  initialFilters: OpsVideoFilters;
};

const VIDEO_TASK_STATUS_OPTIONS = [
  { value: "", label: "All task states" },
  { value: "succeeded", label: "Succeeded" },
  { value: "running", label: "Running" },
  { value: "failed", label: "Failed" },
  { value: "timed_out", label: "Timed out" },
  { value: "skipped", label: "Skipped" },
  { value: "canceled", label: "Canceled" },
];

export function VideosPage({ initialFilters }: VideosPageProps) {
  const router = useRouter();
  const { data: channelsData } = useOpsChannels();
  const { data, isLoading, error } = useOpsVideos(initialFilters);

  const columns: ColumnDef<OpsVideo>[] = [
    {
      header: "Video",
      cell: ({ row }) => (
        <div>
          <div className="max-w-[520px] font-semibold">{row.original.title}</div>
          <div className="text-xs text-slate-500">{compactId(row.original.youtubeVideoId)}</div>
        </div>
      ),
    },
    { header: "Channel", accessorKey: "channelName" },
    { header: "Published", cell: ({ row }) => formatDateTime(row.original.publishedAt) },
    { header: "Duration", accessorKey: "duration" },
    {
      header: "Latest Task",
      cell: ({ row }) => (
        <div className="flex flex-col gap-1">
          <StatusBadge status={row.original.latestTaskStatus} />
          <span className="text-xs text-slate-500">{row.original.latestTaskName ?? "-"}</span>
        </div>
      ),
    },
    {
      header: "Transcript",
      cell: ({ row }) => row.original.transcriptId ?? "-",
    },
    {
      header: "Action",
      cell: ({ row }) => (
        <Link className="ops-button" href={`/videos/${row.original.videoId}`}>
          <Eye size={15} />
          Details
        </Link>
      ),
    },
  ];

  return (
    <>
      <PageHeader title="Videos" />
      <form
        key={JSON.stringify(initialFilters)}
        className="ops-panel mb-4 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          router.push(videosHref(formFilters(event)));
        }}
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <ChannelFilterSelect
            channels={channelsData?.items ?? []}
            value={initialFilters.channelId}
          />
          <FilterInput
            label="Search"
            name="search"
            defaultValue={initialFilters.search}
            placeholder="Title or YouTube ID"
          />
          <FilterSelect
            label="Task status"
            name="taskStatus"
            defaultValue={initialFilters.taskStatus}
            options={VIDEO_TASK_STATUS_OPTIONS}
          />
          <FilterInput label="Limit" name="limit" defaultValue={initialFilters.limit ?? 100} />
        </div>
        <FilterActions resetHref="/videos" />
      </form>
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      <DataTable columns={columns} data={data?.items ?? []} />
      <div className="mt-2 text-xs text-slate-500">Total {data?.total ?? 0}</div>
    </>
  );
}

function formFilters(event: FormEvent<HTMLFormElement>): OpsVideoFilters {
  const form = new FormData(event.currentTarget);
  return {
    channelId: positiveNumberFormValue(form.get("channelId")),
    search: stringFormValue(form.get("search")),
    taskStatus: stringFormValue(form.get("taskStatus")),
    limit: positiveNumberFormValue(form.get("limit")) ?? 100,
  };
}

function videosHref(filters: OpsVideoFilters): string {
  return hrefWithQuery("/videos", filters);
}
