"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { enqueueDemoJob, FINISHED_JOB_STATUSES, getJob, type JobStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<JobStatus, string> = {
  queued: "text-muted-foreground",
  running: "text-foreground",
  succeeded: "text-success",
  failed: "text-destructive",
  cancelled: "text-muted-foreground",
};

export function DemoJobPanel() {
  const [jobId, setJobId] = useState<number | null>(null);

  const enqueue = useMutation({
    mutationFn: enqueueDemoJob,
    onSuccess: (job) => setJobId(job.id),
  });

  const { data: job } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as number),
    enabled: jobId !== null,
    // Poll every 2s until the job reaches a terminal state.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status !== undefined && FINISHED_JOB_STATUSES.includes(status) ? false : 2000;
    },
  });

  const jobInFlight =
    enqueue.isPending ||
    (jobId !== null && (job === undefined || !FINISHED_JOB_STATUSES.includes(job.status)));

  return (
    <Card data-testid="demo-job-panel">
      <CardHeader>
        <CardTitle>Demo background job</CardTitle>
        <CardDescription>
          Proves the job loop: enqueue via API, watch the jobs row go queued → running → succeeded.
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm">
        {job ? (
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span>Status</span>
              <span data-testid="job-status" className={cn("font-medium", STATUS_STYLES[job.status])}>
                {job.status}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span>Progress</span>
              <span data-testid="job-progress">
                {job.progress} / {job.total}
              </span>
            </div>
            {job.error && (
              <div className="flex items-center justify-between">
                <span>Error</span>
                <span className="text-destructive">{job.error}</span>
              </div>
            )}
          </div>
        ) : (
          <p className="text-muted-foreground">
            {enqueue.isError ? "Enqueue failed — is the backend running?" : "No job started yet."}
          </p>
        )}
      </CardContent>
      <CardFooter>
        <Button onClick={() => enqueue.mutate()} disabled={jobInFlight}>
          {jobInFlight ? "Running…" : "Run demo job"}
        </Button>
      </CardFooter>
    </Card>
  );
}
