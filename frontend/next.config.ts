import type { NextConfig } from "next";

// Proxy /api/* to the backend so the browser only ever talks to one origin
// (same-origin cookies later, no CORS surface). BACKEND_URL is set by compose;
// the default matches a locally-run backend.
const nextConfig: NextConfig = {
  // Traced, self-contained server bundle for the prod image (Dockerfile.prod)
  // — `next dev` (used in dev's docker-compose.yml) ignores this entirely.
  output: "standalone",
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
