"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BookOpenText,
  Boxes,
  Cable,
  Database,
  FileText,
  Gauge,
  ListChecks,
  PlaySquare,
  Rows3,
  ScrollText,
} from "lucide-react";

const navItems = [
  { href: "/", label: "Overview", icon: Activity },
  { href: "/channels", label: "Channels", icon: Cable },
  { href: "/videos", label: "Videos", icon: Rows3 },
  { href: "/tasks", label: "Tasks", icon: ListChecks },
  { href: "/jobs", label: "Jobs", icon: PlaySquare },
  { href: "/logs", label: "Logs", icon: ScrollText },
  { href: "/usage", label: "Usage", icon: Gauge },
  { href: "/prompts", label: "Prompts", icon: FileText },
  { href: "/domain-knowledge", label: "Domain", icon: BookOpenText },
  { href: "/erd", label: "ERD", icon: Database },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <>
      <a className="ops-skip-link" href="#main-content">
        Skip to Content
      </a>
      <div className="ops-shell">
        <aside className="ops-sidebar">
          <div className="mb-5 flex items-center gap-2 whitespace-nowrap px-1 md:mb-7">
            <Boxes aria-hidden="true" size={22} color="var(--accent)" />
            <div>
              <div className="text-sm font-bold" translate="no">
                Codex Ops
              </div>
            </div>
          </div>
          <nav aria-label="Ops navigation" className="flex gap-1 md:flex-col">
            {navItems.map((item) => {
              const active =
                pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`flex shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-sm font-semibold ${
                    active
                      ? "border-[color:var(--accent)] bg-[color:var(--accent-soft)] text-[color:var(--accent-strong)]"
                      : "border-transparent text-slate-600 hover:border-slate-200 hover:bg-slate-100"
                  }`}
                >
                  <Icon aria-hidden="true" size={16} />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </aside>
        <main className="ops-main" id="main-content">
          {children}
        </main>
      </div>
    </>
  );
}
