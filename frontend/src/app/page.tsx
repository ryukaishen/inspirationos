import Link from "next/link";

import { DemoJobPanel } from "@/components/demo-job-panel";
import { HealthStatus } from "@/components/health-status";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-6 py-12">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">InspirationOS</h1>
        <p className="text-sm text-muted-foreground">
          <Link className="underline" href="/import">
            Import an Instagram export
          </Link>
          {" · "}
          <Link className="underline" href="/inbox">
            Browse the inbox
          </Link>
          {" · "}
          <Link className="underline" href="/review">
            Fast review
          </Link>
          {" · "}
          <Link className="underline" href="/clusters">
            Clusters
          </Link>
          {" · "}
          <Link className="underline" href="/projects">
            Projects
          </Link>
          {" · "}
          <Link className="underline" href="/settings">
            Settings
          </Link>
        </p>
      </div>
      <HealthStatus />
      <DemoJobPanel />
    </main>
  );
}
