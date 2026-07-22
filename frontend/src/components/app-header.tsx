"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { LogoutButton } from "@/components/logout-button";

/** Minimal persistent bar so logout is reachable from every page — not a
 * nav redesign, just the smallest addition M9 (auth) needs. */
export function AppHeader() {
  const pathname = usePathname();
  if (pathname === "/login") return null;

  return (
    <header className="flex items-center justify-between border-b px-6 py-3">
      <Link href="/" className="text-sm font-semibold tracking-tight">
        InspirationOS
      </Link>
      <LogoutButton />
    </header>
  );
}
