"use client";

import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import { FINISHED_JOB_STATUSES, getJob, type JobRead } from "@/lib/api";

/**
 * Polls `GET /api/jobs/{id}` at 1s intervals until the job reaches a
 * finished status, then calls `onFinished` once. Extracted from the
 * mutation→jobId-state→refetchInterval-poll→invalidate block duplicated
 * across `projects/[id]/page.tsx` (regenerate) and `advisor-panel.tsx`
 * (M7) — M8 adds five more independent job-polling sites (one per career
 * artifact kind) plus export, which is what justifies the extraction now.
 *
 * `onFinished` is read via a ref rather than a hook dependency so callers
 * can pass an inline closure without it retriggering the effect on every
 * render.
 */
export function useJobPolling(jobId: number | null, onFinished?: () => void) {
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as number),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status !== undefined && FINISHED_JOB_STATUSES.includes(status) ? false : 1000;
    },
  });

  const finished = job.data !== undefined && FINISHED_JOB_STATUSES.includes(job.data.status);
  const failed = job.data?.status === "failed";

  const onFinishedRef = useRef(onFinished);
  useEffect(() => {
    onFinishedRef.current = onFinished;
  });

  useEffect(() => {
    if (finished) {
      onFinishedRef.current?.();
    }
  }, [finished, jobId]);

  return {
    job: job.data as JobRead | undefined,
    finished,
    failed,
    running: jobId !== null && !finished,
  };
}
