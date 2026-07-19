// Chains the three analysis jobs (embed -> cluster -> topics), polling each
// job to completion before starting the next. Framework-free and driven by
// injected functions so it is unit-testable without network or timers.

import { FINISHED_JOB_STATUSES, type AnalysisAccepted, type JobRead } from "@/lib/api";

export type AnalysisStep = "embed" | "cluster" | "topics";

export interface AnalysisProgress {
  step: AnalysisStep;
  job: JobRead;
}

export interface AnalysisPipelineDeps {
  triggerEmbed: () => Promise<AnalysisAccepted>;
  triggerCluster: () => Promise<AnalysisAccepted>;
  triggerTopics: () => Promise<AnalysisAccepted>;
  getJob: (jobId: number) => Promise<JobRead>;
  onProgress?: (progress: AnalysisProgress) => void;
  /** Injectable for tests; defaults to a real 1s delay between polls. */
  sleep?: (ms: number) => Promise<void>;
  pollIntervalMs?: number;
}

export class AnalysisStepFailedError extends Error {
  constructor(
    public readonly step: AnalysisStep,
    public readonly job: JobRead,
  ) {
    super(`${step} job ${job.id} finished with status ${job.status}`);
    this.name = "AnalysisStepFailedError";
  }
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

async function runStep(step: AnalysisStep, jobId: number, deps: AnalysisPipelineDeps): Promise<JobRead> {
  const sleep = deps.sleep ?? defaultSleep;
  const interval = deps.pollIntervalMs ?? 1000;
  for (;;) {
    const job = await deps.getJob(jobId);
    deps.onProgress?.({ step, job });
    if (FINISHED_JOB_STATUSES.includes(job.status)) {
      if (job.status !== "succeeded") {
        throw new AnalysisStepFailedError(step, job);
      }
      return job;
    }
    await sleep(interval);
  }
}

/** Runs embed -> cluster -> topics sequentially; a failed step aborts the
 * chain. Returns the final job of each step. */
export async function runAnalysisPipeline(
  deps: AnalysisPipelineDeps,
): Promise<Record<AnalysisStep, JobRead>> {
  const embedAccepted = await deps.triggerEmbed();
  const embed = await runStep("embed", embedAccepted.job_id, deps);
  const clusterAccepted = await deps.triggerCluster();
  const cluster = await runStep("cluster", clusterAccepted.job_id, deps);
  const topicsAccepted = await deps.triggerTopics();
  const topics = await runStep("topics", topicsAccepted.job_id, deps);
  return { embed, cluster, topics };
}
