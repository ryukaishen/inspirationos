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
import { Switch } from "@/components/ui/switch";
import { getSettings, updateEnrichmentSettings } from "@/lib/api";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const { data: settings, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => updateEnrichmentSettings(enabled),
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
