import type { NextConfig } from "next";

// Proxy /api/* to the backend so the browser only ever talks to one origin
// (same-origin cookies later, no CORS surface). BACKEND_URL is set by compose;
// the default matches a locally-run backend.
const nextConfig: NextConfig = {
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
