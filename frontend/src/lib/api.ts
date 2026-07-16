// Typed client for the backend API (reached via the Next.js /api/* proxy).

export type ServiceState = "healthy" | "unreachable";

export interface HealthResponse {
  status: "ok" | "degraded";
  db: ServiceState;
  redis: ServiceState;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface JobRead {
  id: number;
  rq_job_id: string | null;
  kind: string;
  status: JobStatus;
  progress: number;
  total: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export const FINISHED_JOB_STATUSES: readonly JobStatus[] = ["succeeded", "failed", "cancelled"];

export type ImportStatus =
  | "uploaded"
  | "scanning"
  | "scanned"
  | "extracting"
  | "extracted"
  | "failed"
  | "deleted";

export interface ImportRead {
  id: number;
  source: string;
  filename: string;
  size_bytes: number;
  checksum_sha256: string;
  export_format: "json" | "html_detected";
  status: ImportStatus;
  counts: Record<string, number>;
  error: string | null;
  created_at: string;
}

export interface ImportDetail extends ImportRead {
  latest_job: JobRead | null;
}

export interface UploadAccepted {
  import_id: number;
  job_id: number;
}

// Terminal for the M2 pipeline: polling stops on these.
export const FINISHED_IMPORT_STATUSES: readonly ImportStatus[] = [
  "scanned",
  "extracted",
  "failed",
  "deleted",
];

/** Error carrying the backend's structured `detail` payload (code + message). */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string | null,
    message: string,
    public readonly existingImportId: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function errorFromResponse(response: Response, fallback: string): Promise<ApiError> {
  let code: string | null = null;
  let message = fallback;
  let existingImportId: number | null = null;
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") {
      message = detail;
    } else if (detail && typeof detail === "object") {
      const d = detail as { code?: string; message?: string; existing_import_id?: number | null };
      code = d.code ?? null;
      message = d.message ?? fallback;
      existingImportId = d.existing_import_id ?? null;
    }
  } catch {
    // non-JSON error body — keep the fallback message
  }
  return new ApiError(response.status, code, message, existingImportId);
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch("/api/health", { cache: "no-store" });
  // 503 carries a valid "degraded" body — only unexpected statuses are errors.
  if (!response.ok && response.status !== 503) {
    throw new Error(`health request failed with status ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}

export async function enqueueDemoJob(): Promise<JobRead> {
  const response = await fetch("/api/jobs/demo", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!response.ok) {
    throw new Error(`demo job enqueue failed with status ${response.status}`);
  }
  return (await response.json()) as JobRead;
}

export async function getJob(jobId: number): Promise<JobRead> {
  const response = await fetch(`/api/jobs/${jobId}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`job fetch failed with status ${response.status}`);
  }
  return (await response.json()) as JobRead;
}

export async function uploadImportZip(file: File): Promise<UploadAccepted> {
  // Raw streamed body (not multipart) so the backend can enforce its size cap
  // before the body is fully read; the filename is display metadata only.
  const params = new URLSearchParams({ filename: file.name });
  const response = await fetch(`/api/imports/upload?${params.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/zip" },
    body: file,
  });
  if (!response.ok) {
    throw await errorFromResponse(response, `upload failed with status ${response.status}`);
  }
  return (await response.json()) as UploadAccepted;
}

export async function listImports(): Promise<ImportRead[]> {
  const response = await fetch("/api/imports", { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(response, `imports fetch failed with status ${response.status}`);
  }
  return (await response.json()) as ImportRead[];
}

export async function getImport(importId: number): Promise<ImportDetail> {
  const response = await fetch(`/api/imports/${importId}`, { cache: "no-store" });
  if (!response.ok) {
    throw await errorFromResponse(response, `import fetch failed with status ${response.status}`);
  }
  return (await response.json()) as ImportDetail;
}
