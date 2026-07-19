import { describe, expect, it, vi } from "vitest";

import type { JobRead } from "@/lib/api";
import {
  AnalysisStepFailedError,
  runAnalysisPipeline,
  type AnalysisProgress,
} from "@/lib/analysis-pipeline";

function job(id: number, status: JobRead["status"], progress = 0): JobRead {
  return {
    id,
    rq_job_id: `rq-${id}`,
    kind: "embed_batch",
    status,
    progress,
    total: 10,
    error: status === "failed" ? "SomeError" : null,
    created_at: "2026-07-18T00:00:00Z",
    started_at: null,
    finished_at: null,
  };
}

describe("runAnalysisPipeline", () => {
  it("chains embed -> cluster -> topics, polling each job to completion", async () => {
    const jobStates: Record<number, JobRead[]> = {
      1: [job(1, "running", 3), job(1, "succeeded", 10)],
      2: [job(2, "succeeded")],
      3: [job(3, "queued"), job(3, "running"), job(3, "succeeded")],
    };
    const getJob = vi.fn(async (jobId: number) => {
      const states = jobStates[jobId];
      return states.length > 1 ? (states.shift() as JobRead) : states[0];
    });
    const progress: AnalysisProgress[] = [];

    const result = await runAnalysisPipeline({
      triggerEmbed: vi.fn(async () => ({ job_id: 1 })),
      triggerCluster: vi.fn(async () => ({ job_id: 2 })),
      triggerTopics: vi.fn(async () => ({ job_id: 3 })),
      getJob,
      onProgress: (update) => progress.push(update),
      sleep: async () => {},
    });

    expect(result.embed.status).toBe("succeeded");
    expect(result.cluster.id).toBe(2);
    expect(result.topics.id).toBe(3);
    expect(progress.map((p) => p.step)).toEqual([
      "embed",
      "embed",
      "cluster",
      "topics",
      "topics",
      "topics",
    ]);
  });

  it("aborts the chain when a step fails and never starts the next step", async () => {
    const triggerCluster = vi.fn(async () => ({ job_id: 2 }));
    const triggerTopics = vi.fn(async () => ({ job_id: 3 }));

    await expect(
      runAnalysisPipeline({
        triggerEmbed: async () => ({ job_id: 1 }),
        triggerCluster,
        triggerTopics,
        getJob: async () => job(1, "failed"),
        sleep: async () => {},
      }),
    ).rejects.toThrowError(AnalysisStepFailedError);

    expect(triggerCluster).not.toHaveBeenCalled();
    expect(triggerTopics).not.toHaveBeenCalled();
  });
});
