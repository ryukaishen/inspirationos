"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  ApiError,
  exportDownloadUrl,
  getExport,
  requestExport,
  type ExportBundleFormat,
} from "@/lib/api";
import { useJobPolling } from "@/lib/use-job-polling";

function ExportButton({
  format,
  projectId,
  label,
}: {
  format: ExportBundleFormat;
  projectId?: number;
  label: string;
}) {
  const queryClient = useQueryClient();
  const [exportId, setExportId] = useState<number | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);

  const exportRead = useQuery({
    queryKey: ["export", exportId],
    queryFn: () => getExport(exportId as number),
    enabled: exportId !== null,
  });

  const request = useMutation({
    mutationFn: () => requestExport(format, projectId),
    onSuccess: (accepted) => {
      setExportId(accepted.export_id);
      setJobId(accepted.job_id);
    },
  });

  const { job, running, failed } = useJobPolling(jobId, () => {
    void queryClient.invalidateQueries({ queryKey: ["export", exportId] });
  });

  const ready = exportRead.data?.ready === true;

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={`export-${format}`}>
      <Button
        size="sm"
        variant="outline"
        disabled={running}
        data-testid={`export-${format}-request`}
        onClick={() => request.mutate()}
      >
        {running ? "Exporting…" : `Export ${label}`}
      </Button>
      {ready && exportId !== null && (
        <a
          className="text-sm underline"
          data-testid={`export-${format}-download`}
          href={exportDownloadUrl(exportId)}
          download
        >
          Download
        </a>
      )}
      {(request.isError || failed) && (
        <span className="text-xs text-destructive" data-testid={`export-${format}-error`}>
          {request.error instanceof ApiError
            ? request.error.message
            : `Export failed (${job?.error ?? "unknown error"}).`}
        </span>
      )}
    </div>
  );
}

export function ExportPanel({ projectId }: { projectId?: number }) {
  return (
    <section className="space-y-2 rounded-lg border bg-card p-4" data-testid="export-panel">
      <div>
        <p className="font-medium">Export</p>
        <p className="text-sm text-muted-foreground">
          {projectId !== undefined
            ? "Download this project as Markdown or schema-stable JSON."
            : "Download the full project library as Markdown or schema-stable JSON."}
        </p>
      </div>
      <div className="flex flex-wrap gap-4">
        <ExportButton format="markdown" projectId={projectId} label="Markdown" />
        <ExportButton format="json" projectId={projectId} label="JSON" />
      </div>
    </section>
  );
}
