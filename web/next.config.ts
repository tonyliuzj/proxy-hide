import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  devIndicators: false,
  async rewrites() {
    const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    return [
      { source: "/api/v1/:path*", destination: `${apiUrl}/api/v1/:path*` },
      { source: "/health", destination: `${apiUrl}/health` },
      { source: "/health/:path*", destination: `${apiUrl}/health/:path*` },
    ];
  },
};

export default nextConfig;
