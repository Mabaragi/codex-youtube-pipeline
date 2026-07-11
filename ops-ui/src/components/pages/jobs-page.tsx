import Link from "next/link";
import { PageHeader } from "@/components/page-header";
import { InlineNotice } from "@/components/ui-primitives";

export function JobsPage() {
  return (
    <>
      <PageHeader title="Work History" description="Pipeline jobs were unified into durable work items and attempts." />
      <InlineNotice tone="info">
        Job state, retries, leases, and attempt history now live in Work Items. <Link className="font-semibold underline" href="/tasks">Open Work Items</Link>
      </InlineNotice>
    </>
  );
}
