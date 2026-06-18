import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  basePath: "/ops",
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname, "../"),
  poweredByHeader: false,
};

export default nextConfig;
