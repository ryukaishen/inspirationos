"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ConfirmDeleteDialog } from "@/components/deletion/confirm-delete-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  AI_PROVIDERS,
  ApiError,
  FINISHED_JOB_STATUSES,
  getCareerProfile,
  getCurrentUser,
  getJob,
  getSettings,
  requestWipe,
  updateAiSettings,
  updateCareerProfile,
  updateEnrichmentSettings,
  type AiProvider,
} from "@/lib/api";

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [aiProvider, setAiProvider] = useState<AiProvider>("mock");
  const [generationModel, setGenerationModel] = useState("");
  const [fastModel, setFastModel] = useState("");
  const [budget, setBudget] = useState("");
  const [aiFormReady, setAiFormReady] = useState(false);
  const [background, setBackground] = useState("");
  const [skills, setSkills] = useState("");
  const [targetDomains, setTargetDomains] = useState("");
  const [experienceLevel, setExperienceLevel] = useState("");
  const [timeConstraint, setTimeConstraint] = useState("");
  const [computeConstraint, setComputeConstraint] = useState("");
  const [interests, setInterests] = useState("");
  const [careerFormReady, setCareerFormReady] = useState(false);
  const [wipeOpen, setWipeOpen] = useState(false);
  const [wipeJobId, setWipeJobId] = useState<number | null>(null);

  const { data: settings, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });
  const { data: careerProfile } = useQuery({
    queryKey: ["career-profile"],
    queryFn: getCareerProfile,
  });
  const { data: currentUser } = useQuery({
    queryKey: ["current-user"],
    queryFn: getCurrentUser,
  });

  // Initialize the AI form once from the loaded settings (render-time state
  // adjustment); afterwards the drafts are user-owned until saved.
  if (settings && !aiFormReady) {
    setAiProvider(settings.ai_provider);
    setGenerationModel(settings.model_overrides.generation ?? "");
    setFastModel(settings.model_overrides.fast ?? "");
    setBudget(settings.monthly_budget_usd === null ? "" : String(settings.monthly_budget_usd));
    setAiFormReady(true);
  }
  if (careerProfile && !careerFormReady) {
    setBackground(careerProfile.background_md ?? "");
    setSkills(careerProfile.skills.join(", "));
    setTargetDomains(careerProfile.target_domains.join(", "));
    setExperienceLevel(careerProfile.experience_level ?? "");
    setTimeConstraint(String(careerProfile.constraints.time ?? ""));
    setComputeConstraint(String(careerProfile.constraints.compute ?? ""));
    setInterests(careerProfile.interests_md ?? "");
    setCareerFormReady(true);
  }

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => updateEnrichmentSettings(enabled),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const saveAi = useMutation({
    mutationFn: () =>
      updateAiSettings({
        ai_provider: aiProvider,
        model_overrides: {
          generation: generationModel.trim() || null,
          fast: fastModel.trim() || null,
        },
        monthly_budget_usd: budget.trim() === "" ? null : Number(budget),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const saveCareer = useMutation({
    mutationFn: () => {
      const constraints: Record<string, string> = {};
      if (timeConstraint.trim()) constraints.time = timeConstraint.trim();
      if (computeConstraint.trim()) constraints.compute = computeConstraint.trim();
      return updateCareerProfile({
        background_md: background.trim() || null,
        skills: parseList(skills),
        target_domains: parseList(targetDomains),
        experience_level: experienceLevel.trim() || null,
        constraints,
        interests_md: interests.trim() || null,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["career-profile"] });
    },
  });

  const wipe = useMutation({
    mutationFn: (confirmEmail: string) => requestWipe(confirmEmail),
    // Close the dialog once the job is accepted; progress/report render on
    // the page itself, not inside the (now-closed) confirmation dialog.
    onSuccess: (accepted) => {
      setWipeOpen(false);
      setWipeJobId(accepted.job_id);
    },
  });

  const wipeJob = useQuery({
    queryKey: ["job", "wipe", wipeJobId],
    queryFn: () => getJob(wipeJobId as number),
    enabled: wipeJobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status !== undefined && FINISHED_JOB_STATUSES.includes(status) ? false : 1500;
    },
  });
  const wipeSucceeded = wipeJob.data?.status === "succeeded";
  const wipeReport = wipeSucceeded ? (wipeJob.data?.payload.report as Record<string, unknown>) : null;

  function handleToggle(next: boolean) {
    if (next) {
      // Disclosure-then-consent: the toggle alone never enables anything.
      setConfirmOpen(true);
      return;
    }
    toggle.mutate(false);
  }

  function confirmEnable() {
    setConfirmOpen(false);
    toggle.mutate(true);
  }

  return (
    <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-6 py-12">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Enrichment fetches public metadata (oEmbed, then OpenGraph) for saved links.
        </p>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {settings && (
        <div className="space-y-2 rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="font-medium">Metadata enrichment</p>
              <p className="text-sm text-muted-foreground">
                Off by default. Enabling only unlocks the per-item / selection / group Enrich
                action — nothing is fetched automatically.
              </p>
            </div>
            <Switch
              aria-label="Enable metadata enrichment"
              data-testid="enrichment-toggle"
              checked={settings.enrichment_enabled}
              onCheckedChange={handleToggle}
              disabled={toggle.isPending}
            />
          </div>
          {settings.enrichment_consent_at && (
            <p className="text-xs text-muted-foreground" data-testid="consent-timestamp">
              Consent given {new Date(settings.enrichment_consent_at).toLocaleString()}
            </p>
          )}
        </div>
      )}

      {settings && (
        <div className="space-y-3 rounded-lg border bg-card p-4">
          <div>
            <p className="font-medium">AI provider</p>
            <p className="text-sm text-muted-foreground">
              The mock provider works fully offline and is the default. API keys are read
              from environment variables only — they are never stored here.
            </p>
          </div>
          <label className="block text-sm">
            Provider
            <select
              aria-label="AI provider"
              data-testid="ai-provider-select"
              className="mt-1 block w-full rounded-md border bg-transparent px-3 py-2 text-sm"
              value={aiProvider}
              onChange={(event) => setAiProvider(event.target.value as AiProvider)}
            >
              {AI_PROVIDERS.map((provider) => (
                <option key={provider} value={provider}>
                  {provider}
                </option>
              ))}
            </select>
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm">
              Generation model override
              <Input
                data-testid="ai-model-generation"
                className="mt-1"
                value={generationModel}
                onChange={(event) => setGenerationModel(event.target.value)}
                placeholder="provider default"
              />
            </label>
            <label className="block text-sm">
              Fast model override
              <Input
                data-testid="ai-model-fast"
                className="mt-1"
                value={fastModel}
                onChange={(event) => setFastModel(event.target.value)}
                placeholder="provider default"
              />
            </label>
          </div>
          <label className="block text-sm">
            Monthly budget (USD)
            <Input
              data-testid="ai-budget-input"
              className="mt-1 max-w-40"
              type="number"
              min="0"
              step="0.5"
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
              placeholder="env default"
            />
          </label>
          <div className="flex items-center gap-3">
            <Button
              data-testid="ai-save"
              disabled={saveAi.isPending}
              onClick={() => saveAi.mutate()}
            >
              Save AI settings
            </Button>
            {saveAi.isSuccess && (
              <p className="text-xs text-muted-foreground" data-testid="ai-saved">
                Saved.
              </p>
            )}
            {saveAi.isError && (
              <p className="text-xs text-destructive" data-testid="ai-save-error">
                Saving failed — check the values.
              </p>
            )}
          </div>
        </div>
      )}

      <div className="space-y-3 rounded-lg border bg-card p-4" data-testid="career-profile">
        <div>
          <p className="font-medium">Career profile</p>
          <p className="text-sm text-muted-foreground">
            Grounds project generation and the advisor: background, skills, target domains,
            and constraints. Sent only to your configured AI provider — never logged.
          </p>
        </div>
        <label className="block text-sm">
          Background
          <Textarea
            data-testid="career-background"
            className="mt-1"
            rows={3}
            value={background}
            onChange={(event) => setBackground(event.target.value)}
            placeholder="Who you are, what you've built, where you're headed…"
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            Skills (comma-separated)
            <Input
              data-testid="career-skills"
              className="mt-1"
              value={skills}
              onChange={(event) => setSkills(event.target.value)}
              placeholder="python, sql, pytorch"
            />
          </label>
          <label className="block text-sm">
            Target domains (comma-separated)
            <Input
              data-testid="career-domains"
              className="mt-1"
              value={targetDomains}
              onChange={(event) => setTargetDomains(event.target.value)}
              placeholder="data science, healthcare ai"
            />
          </label>
          <label className="block text-sm">
            Experience level
            <Input
              data-testid="career-experience"
              className="mt-1"
              value={experienceLevel}
              onChange={(event) => setExperienceLevel(event.target.value)}
              placeholder="student / junior / intermediate…"
            />
          </label>
          <label className="block text-sm">
            Time constraint
            <Input
              data-testid="career-time"
              className="mt-1"
              value={timeConstraint}
              onChange={(event) => setTimeConstraint(event.target.value)}
              placeholder="e.g. 10 hours/week"
            />
          </label>
          <label className="block text-sm">
            Compute constraint
            <Input
              data-testid="career-compute"
              className="mt-1"
              value={computeConstraint}
              onChange={(event) => setComputeConstraint(event.target.value)}
              placeholder="e.g. laptop only"
            />
          </label>
        </div>
        <label className="block text-sm">
          Interests
          <Textarea
            data-testid="career-interests"
            className="mt-1"
            rows={2}
            value={interests}
            onChange={(event) => setInterests(event.target.value)}
            placeholder="Topics you want your projects to explore…"
          />
        </label>
        <div className="flex items-center gap-3">
          <Button
            data-testid="career-save"
            disabled={saveCareer.isPending}
            onClick={() => saveCareer.mutate()}
          >
            Save career profile
          </Button>
          {saveCareer.isSuccess && (
            <p className="text-xs text-muted-foreground" data-testid="career-saved">
              Saved.
            </p>
          )}
          {saveCareer.isError && (
            <p className="text-xs text-destructive" data-testid="career-save-error">
              Saving failed — check the values.
            </p>
          )}
        </div>
      </div>

      <div
        className="space-y-3 rounded-lg border border-destructive/40 bg-card p-4"
        data-testid="danger-zone"
      >
        <div>
          <p className="font-medium text-destructive">Danger zone</p>
          <p className="text-sm text-muted-foreground">
            Permanently deletes every table except your account, and every stored file. Runs as a
            background job and produces a verification report.
          </p>
        </div>
        <Button
          size="sm"
          variant="destructive"
          data-testid="wipe-open"
          disabled={!currentUser}
          onClick={() => setWipeOpen(true)}
        >
          Delete all application data
        </Button>
        {wipeJobId !== null && !wipeSucceeded && (
          <p className="text-xs text-muted-foreground" data-testid="wipe-in-progress">
            Wipe job {wipeJob.data?.status ?? "queued"}…
          </p>
        )}
        {wipeReport && (
          <pre
            className="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs"
            data-testid="wipe-report"
          >
            {JSON.stringify(wipeReport, null, 2)}
          </pre>
        )}
      </div>

      {currentUser && (
        <ConfirmDeleteDialog
          open={wipeOpen}
          onOpenChange={setWipeOpen}
          title="Delete all application data?"
          description="Every import, item, project, artifact, and stored file is removed permanently. Only your account survives."
          confirmValue={currentUser.email}
          confirmLabel="Wipe everything"
          onConfirm={() => wipe.mutate(currentUser.email)}
          isPending={wipe.isPending}
          error={
            wipe.error instanceof ApiError
              ? wipe.error.message
              : wipe.isError
                ? "Wipe request failed."
                : null
          }
          testIdPrefix="wipe"
        />
      )}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogHeader>
          <DialogTitle>Enable metadata enrichment?</DialogTitle>
          <DialogDescription>
            Your saved URLs will be sent over the network to fetch public oEmbed/OpenGraph
            metadata (title, caption, author). Requests are anonymous, rate-limited, and only
            ever triggered by an explicit Enrich action on an item, selection, or group —
            never a global crawl. Expect a low hit rate: Instagram blocks anonymous access
            aggressively.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button data-testid="dialog-cancel" variant="ghost" onClick={() => setConfirmOpen(false)}>
            Cancel
          </Button>
          <Button data-testid="consent-confirm" onClick={confirmEnable}>
            Enable
          </Button>
        </DialogFooter>
      </Dialog>
    </main>
  );
}
