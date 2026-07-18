"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FINISHED_IMPORT_STATUSES, getImport, type ImportStatus } from "@/lib/api";

// Mirrors backend's SELECTABLE_STATUSES in app/api/conversations.py — a
// failed import with a stored file stays selectable so a failed extract can
// be retried.
const SELECTABLE_IMPORT_STATUSES: readonly ImportStatus[] = ["scanned", "extracted", "failed"];

export default function ImportDetailPage() {
  const params = useParams<{ id: string }>();
  const importId = Number(params.id);

  const { data: detail, isError } = useQuery({
    queryKey: ["import", importId],
    queryFn: () => getImport(importId),
    enabled: Number.isInteger(importId) && importId > 0,
    // Poll every 2s until the import reaches a terminal state.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status !== undefined && FINISHED_IMPORT_STATUSES.includes(status) ? false : 2000;
    },
  });

  return (
    <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-6 py-12">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Import detail</h1>
        <p className="text-sm text-muted-foreground">
          <Link className="underline" href="/import">
            ← Back to imports
          </Link>
        </p>
      </div>
      <Card data-testid="import-detail">
        <CardHeader>
          <CardTitle>{detail ? detail.filename : "Loading…"}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          {isError && <p className="text-destructive">Import not found.</p>}
          {detail && (
            <>
              <div className="flex items-center justify-between">
                <span>Status</span>
                <span data-testid="import-status" className="font-medium">
                  {detail.status}
                </span>
              </div>
              {detail.counts.total_entries !== undefined && (
                <div className="flex items-center justify-between">
                  <span>Scan counts</span>
                  <span data-testid="import-counts">
                    {detail.counts.total_entries} entries · {detail.counts.message_files} message
                    files
                  </span>
                </div>
              )}
              {detail.error && (
                <div className="flex items-center justify-between gap-4">
                  <span>Error</span>
                  <span className="text-destructive">{detail.error}</span>
                </div>
              )}
              {detail.latest_job && (
                <div className="flex items-center justify-between">
                  <span>Scan job</span>
                  <span data-testid="scan-job-status">
                    {detail.latest_job.status} ({detail.latest_job.progress}/
                    {detail.latest_job.total})
                  </span>
                </div>
              )}
              {/* html_detected imports never have a stored file (mirrors the
                  backend's no_stored_file guard in conversations.py) */}
              {detail.export_format === "json" &&
                SELECTABLE_IMPORT_STATUSES.includes(detail.status) && (
                  <p className="pt-2">
                    <Link className="underline" href={`/import/${importId}/conversations`}>
                      Select conversations →
                    </Link>
                  </p>
                )}
            </>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
