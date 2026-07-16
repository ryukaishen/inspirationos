"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiError, uploadImportZip } from "@/lib/api";

export function ImportUploader() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);

  const upload = useMutation({
    mutationFn: uploadImportZip,
    onSuccess: async (accepted) => {
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
      router.push(`/import/${accepted.import_id}`);
    },
  });

  const error = upload.error;
  const duplicateImportId =
    error instanceof ApiError && error.code === "duplicate" ? error.existingImportId : null;

  return (
    <Card data-testid="import-uploader">
      <CardHeader>
        <CardTitle>Upload Instagram export</CardTitle>
        <CardDescription>
          Upload the ZIP from Instagram&apos;s &quot;Download your information&quot; (JSON format).
          The scan runs fully offline — no message content leaves this machine.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <input
          type="file"
          accept=".zip,application/zip"
          aria-label="Export ZIP file"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        {error && (
          <div data-testid="upload-error" className="space-y-1 text-destructive">
            <p>{error.message}</p>
            {duplicateImportId !== null && (
              <p>
                <Link className="underline" href={`/import/${duplicateImportId}`}>
                  View the existing import
                </Link>
              </p>
            )}
          </div>
        )}
      </CardContent>
      <CardFooter>
        <Button onClick={() => file && upload.mutate(file)} disabled={!file || upload.isPending}>
          {upload.isPending ? "Uploading…" : "Upload"}
        </Button>
      </CardFooter>
    </Card>
  );
}
