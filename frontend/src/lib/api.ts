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
