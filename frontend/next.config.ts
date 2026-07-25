import type { NextConfig } from "next";

// Proxy /api/* to the backend so the browser only ever talks to one origin
// (same-origin cookies later, no CORS surface). BACKEND_URL is set by compose;
// the default matches a locally-run backend.
const nextConfig: NextConfig = {
  // Traced, self-contained server bundle for the prod image (Dockerfile.prod)
  // — `next dev` (used in dev's docker-compose.yml) ignores this entirely.
  output: "standalone",
  experimental: {
    // src/proxy.ts runs on every request (redirect-to-/login UX check), and
    // Next 16 caps how much body the proxy layer will buffer/forward at 10MB
    // by default — silently truncating and then resetting the connection for
    // anything larger, which is what killed real Instagram-export uploads
    // (multi-GB ZIPs) with an opaque "socket hang up" rather than a clean
    // error. proxy.ts never reads the body itself (only checks the session
    // cookie), so raising this is safe. Matches the raised backend
    // MAX_UPLOAD_SIZE_MB (see .env.example) with headroom above it.
    proxyClientMaxBodySize: "5gb",
  },
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
