"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Boxes,
  Cable,
  Database,
  ListChecks,
  PlaySquare,
  Rows3,
} from "lucide-react";

const navItems = [
  { href: "/", label: "Overview", icon: Activity },
  { href: "/channels", label: "Channels", icon: Cable },
  { href: "/videos", label: "Videos", icon: Rows3 },
  { href: "/tasks", label: "Tasks", icon: ListChecks },
  { href: "/jobs", label: "Jobs", icon: PlaySquare },
  { href: "/erd", label: "ERD", icon: Database },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="ops-shell">
      <aside className="ops-sidebar">
        <div className="mb-7 flex items-center gap-2">
          <Boxes size={22} color="var(--accent)" />
          <div>
            <div className="text-sm font-bold">Codex Ops</div>
          </div>
        </div>
        <nav className="flex flex-col gap-1">
          {navItems.map((item) => {
            const active =
              pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm font-semibold ${
                  active
                    ? "bg-[color:var(--accent)] text-white"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <Icon size={16} />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <main className="ops-main">{children}</main>
    </div>
  );
}
