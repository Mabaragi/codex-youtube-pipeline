import { redirect } from "next/navigation";

export default function LegacyJobsPage() { redirect("/executions?tab=batches"); }
