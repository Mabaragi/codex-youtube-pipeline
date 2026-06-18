"use client";

import dynamic from "next/dynamic";

const ErdPage = dynamic(
  () => import("@/components/pages/erd-page").then((module) => module.ErdPage),
  {
    ssr: false,
    loading: () => <div className="ops-panel p-4 text-sm text-slate-600">Loading ERD...</div>,
  },
);

export default function Page() {
  return <ErdPage />;
}
