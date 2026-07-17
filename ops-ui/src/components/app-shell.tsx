"use client";

import {
  Activity,
  BookOpen,
  Boxes,
  Captions,
  ChartNoAxesCombined,
  CircleAlert,
  Clapperboard,
  FileClock,
  Gauge,
  ListTodo,
  Megaphone,
  Network,
  Radio,
  ScrollText,
  SlidersHorizontal,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/cn";

type NavItemValue = { href: string; label: string; icon: LucideIcon };
type NavigationGroup = { label: string; items: readonly NavItemValue[] };

const NAVIGATION: readonly NavigationGroup[] = [
  { label: "운영", items: [
    { href: "/", label: "Command Center", icon: Gauge },
    { href: "/operations", label: "실행", icon: SlidersHorizontal },
    { href: "/executions", label: "작업 추적", icon: ListTodo },
    { href: "/incidents", label: "Incident", icon: CircleAlert },
  ] },
  { label: "콘텐츠", items: [
    { href: "/content/videos", label: "영상", icon: Clapperboard },
    { href: "/content/transcripts", label: "자막", icon: Captions },
    { href: "/publishing", label: "퍼블리시", icon: Megaphone },
  ] },
  { label: "구성", items: [
    { href: "/configuration/channels", label: "채널 & 스트리머", icon: Radio },
    { href: "/configuration/knowledge", label: "도메인 지식", icon: BookOpen },
    { href: "/configuration/prompts", label: "프롬프트", icon: ScrollText },
  ] },
  { label: "관측", items: [
    { href: "/observability/events", label: "운영 이벤트", icon: FileClock },
    { href: "/observability/usage", label: "Codex 사용량", icon: ChartNoAxesCombined },
    { href: "/system/schema", label: "Schema", icon: Network },
  ] },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15.5rem_minmax(0,1fr)]">
      <a className="skip-link" href="#main-content">본문으로 건너뛰기</a>
      <aside className="hidden min-h-screen border-r bg-[var(--surface)] lg:sticky lg:top-0 lg:block lg:h-screen lg:overflow-y-auto">
        <ShellBrand />
        <nav aria-label="주요 메뉴" className="grid gap-5 px-3 py-4">
          {NAVIGATION.map((group) => (
            <div key={group.label}>
              <p className="mb-1.5 px-2 text-[11px] font-semibold uppercase text-[var(--muted)]">{group.label}</p>
              <ul className="grid gap-0.5">
                {group.items.map((item) => <NavItem key={item.href} item={item} pathname={pathname} />)}
              </ul>
            </div>
          ))}
        </nav>
      </aside>
      <div className="min-w-0">
        <header className="sticky top-0 z-40 flex min-h-14 items-center justify-between border-b bg-[var(--background)]/95 px-4 backdrop-blur lg:px-6">
          <div className="lg:hidden"><ShellBrand compact /></div>
          <div className="hidden items-center gap-2 text-xs text-[var(--muted)] lg:flex">
            <Activity aria-hidden="true" className="size-3.5 text-[var(--success)]" />
            로컬 운영 콘솔
          </div>
          <ThemeToggle />
        </header>
        <nav aria-label="모바일 주요 메뉴" className="ops-scrollbar flex gap-1 overflow-x-auto border-b bg-[var(--surface)] p-2 lg:hidden">
          {NAVIGATION.flatMap((group) => group.items).map((item) => <MobileNavItem key={item.href} item={item} pathname={pathname} />)}
        </nav>
        <main id="main-content" className="ops-grid min-w-0 p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] lg:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}

function ShellBrand({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/" className={cn("flex min-h-14 items-center gap-2 px-4 font-semibold", !compact && "border-b")}>
      <span className="grid size-7 place-items-center rounded bg-[var(--accent)] text-white"><Boxes aria-hidden="true" className="size-4" /></span>
      <span>Opus Ops <span className="text-xs text-[var(--muted)]">v2</span></span>
    </Link>
  );
}

function NavItem({ item, pathname }: { item: NavItemValue; pathname: string }) {
  const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
  const Icon = item.icon;
  return (
    <li>
      <Link href={item.href} aria-current={active ? "page" : undefined} className={cn("flex min-h-10 items-center gap-2 rounded-md px-2.5 text-sm text-[var(--muted)] transition-[background-color,color] hover:bg-[var(--surface-muted)] hover:text-[var(--foreground)]", active && "bg-[var(--accent-soft)] font-semibold text-[var(--accent-strong)]")}>
        <Icon aria-hidden="true" className="size-4" />{item.label}
      </Link>
    </li>
  );
}

function MobileNavItem({ item, pathname }: { item: NavItemValue; pathname: string }) {
  const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
  const Icon = item.icon;
  return <Link href={item.href} aria-current={active ? "page" : undefined} className={cn("flex min-h-11 shrink-0 items-center gap-1.5 rounded-md px-3 text-xs text-[var(--muted)]", active && "bg-[var(--accent-soft)] font-semibold text-[var(--accent-strong)]")}><Icon aria-hidden="true" className="size-4" />{item.label}</Link>;
}
