"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FINISHED_IMPORT_STATUSES, listImports, type ImportRead, type ImportStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<ImportStatus, string> = {
  uploaded: "text-muted-foreground",
  scanning: "text-foreground",
  scanned: "text-success",
  extracting: "text-foreground",
  extracted: "text-success",
  failed: "text-destructive",
  deleted: "text-muted-foreground",
};

function countsSummary(row: ImportRead): string | null {
  if (row.counts.total_entries === undefined) {
    return null;
  }
  return `${row.counts.total_entries} entries · ${row.counts.message_files} message files`;
}

export function ImportList() {
  const { data: imports } = useQuery({
    queryKey: ["imports"],
    queryFn: listImports,
    // Poll every 2s while any import is still moving through the pipeline.
    refetchInterval: (query) => {
      const rows = query.state.data;
      if (rows === undefined) {
        return 2000;
      }
      return rows.some((row) => !FINISHED_IMPORT_STATUSES.includes(row.status)) ? 2000 : false;
    },
  });

  return (
    <Card data-testid="import-list">
      <CardHeader>
        <CardTitle>Imports</CardTitle>
      </CardHeader>
      <CardContent className="text-sm">
        {imports === undefined ? (
          <p className="text-muted-foreground">Loading…</p>
        ) : imports.length === 0 ? (
          <p className="text-muted-foreground">No imports yet.</p>
        ) : (
          <ul className="divide-y">
            {imports.map((row) => (
              <li key={row.id} className="py-2" data-testid="import-row">
                <div className="flex items-center justify-between gap-4">
                  <Link className="truncate font-medium underline" href={`/import/${row.id}`}>
                    {row.filename}
                  </Link>
                  <span
                    data-testid="import-row-status"
                    className={cn("shrink-0 font-medium", STATUS_STYLES[row.status])}
                  >
                    {row.status}
                  </span>
                </div>
                {countsSummary(row) && (
                  <p className="text-muted-foreground">{countsSummary(row)}</p>
                )}
                {row.error && <p className="text-destructive">{row.error}</p>}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
