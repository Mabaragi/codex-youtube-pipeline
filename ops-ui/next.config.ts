import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  basePath: "/ops",
  distDir: process.env.CODEX_OPS_BUILD_DIR ?? ".next",
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname, "../"),
  poweredByHeader: false,
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
};

export default nextConfig;
