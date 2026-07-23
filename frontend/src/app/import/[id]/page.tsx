"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";

import { ConfirmDeleteDialog } from "@/components/deletion/confirm-delete-dialog";
import { VerificationReport } from "@/components/imports/verification-report";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  ApiError,
  FINISHED_IMPORT_STATUSES,
  deleteImport,
  getImport,
  getImportVerification,
  type ImportStatus,
} from "@/lib/api";

// Mirrors backend's SELECTABLE_STATUSES in app/api/conversations.py — a
// failed import with a stored file stays selectable so a failed extract can
// be retried.
const SELECTABLE_IMPORT_STATUSES: readonly ImportStatus[] = ["scanned", "extracted", "failed"];

export default function ImportDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const importId = Number(params.id);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [cascade, setCascade] = useState(false);

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

  const removeImport = useMutation({
    mutationFn: (confirmText: string) => deleteImport(importId, confirmText, cascade),
    onSuccess: () => {
      setDeleteOpen(false);
      router.push("/import");
    },
  });

  // Fetched once a scan has had a chance to run, so the report reflects real
  // counts rather than the all-zero pre-scan state.
  const { data: verification } = useQuery({
    queryKey: ["import-verification", importId],
    queryFn: () => getImportVerification(importId),
    enabled:
      Number.isInteger(importId) && importId > 0 && detail !== undefined && detail.status !== "uploaded",
    refetchInterval: () => {
      const status = detail?.status;
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
              {detail.status !== "deleted" && (
                <div className="border-t pt-3">
                  <Button
                    size="sm"
                    variant="destructive"
                    data-testid="import-delete-open"
                    onClick={() => setDeleteOpen(true)}
                  >
                    Delete import
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {verification && (
        <Card data-testid="verification-report-card">
          <CardHeader>
            <CardTitle>Verification report</CardTitle>
          </CardHeader>
          <CardContent>
            <VerificationReport report={verification} />
          </CardContent>
        </Card>
      )}

      {detail && (
        <ConfirmDeleteDialog
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
          title="Delete raw import data?"
          description="The stored ZIP, conversations, and messages are always removed. Choose whether derived inspiration items are kept (source references cleared) or deleted too."
          confirmValue={detail.filename}
          onConfirm={() => removeImport.mutate(detail.filename)}
          isPending={removeImport.isPending}
          error={
            removeImport.error instanceof ApiError
              ? removeImport.error.message
              : removeImport.isError
                ? "Delete failed."
                : null
          }
          testIdPrefix="import-delete"
        >
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              data-testid="import-delete-cascade"
              checked={cascade}
              onChange={(event) => setCascade(event.target.checked)}
            />
            Also delete the derived inspiration items (default keeps them, with source references
            cleared)
          </label>
        </ConfirmDeleteDialog>
      )}
    </main>
  );
}
