"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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
import {
  AI_PROVIDERS,
  getSettings,
  updateAiSettings,
  updateEnrichmentSettings,
  type AiProvider,
} from "@/lib/api";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [aiProvider, setAiProvider] = useState<AiProvider>("mock");
  const [generationModel, setGenerationModel] = useState("");
  const [fastModel, setFastModel] = useState("");
  const [budget, setBudget] = useState("");
  const [aiFormReady, setAiFormReady] = useState(false);

  const { data: settings, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
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
