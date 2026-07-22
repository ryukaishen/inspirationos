import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// UX convenience only — the backend's get_current_user dependency (see
// backend/app/api/deps.py) is the real security boundary; every non-auth API
// route rejects an unauthenticated request regardless of what this does.
// Named `proxy.ts` (not `middleware.ts`): this Next.js version renamed the
// file convention — see node_modules/next/dist/docs/.../proxy.md.
const SESSION_COOKIE_NAME = "session_id";
const PUBLIC_PATHS = ["/login"];

export function proxy(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.has(SESSION_COOKIE_NAME);

  if (!hasSession && !PUBLIC_PATHS.includes(pathname)) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  if (hasSession && pathname === "/login") {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    // Everything except API routes (backend enforces its own auth), Next
    // internals, and static assets.
    "/((?!api|_next/static|_next/image|favicon.ico).*)",
  ],
};
