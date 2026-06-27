import type { Metadata, Viewport } from "next";
import "@xyflow/react/dist/style.css";
import "./globals.css";
import { AppShell } from "@/components/app-shell";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Codex Ops",
  description: "Operational console for Codex SDK API workflows.",
};

export const viewport: Viewport = {
  themeColor: "#f6f7f9",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
