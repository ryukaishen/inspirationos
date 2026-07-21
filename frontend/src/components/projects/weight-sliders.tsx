"use client";

import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import {
  DEFAULT_WEIGHT,
  DIMENSION_LABELS,
  MAX_WEIGHT,
  MIN_WEIGHT,
  SCORE_DIMENSIONS,
  type ScoreDimension,
  type Weights,
} from "@/lib/scoring";

export interface WeightSlidersProps {
  weights: Weights;
  // Pure/controlled like filter-bar: the page owns the state, so every slider
  // move re-ranks instantly via the page's useMemo — no API call involved.
  onWeightChange: (dimension: ScoreDimension, value: number) => void;
  onSave: () => void;
  saving: boolean;
  saved: boolean;
  saveError: string | null;
}

export function WeightSliders({
  weights,
  onWeightChange,
  onSave,
  saving,
  saved,
  saveError,
}: WeightSlidersProps) {
  return (
    <div className="space-y-3 rounded-lg border bg-card p-4" data-testid="weight-sliders">
      <div>
        <p className="font-medium">Ranking weights</p>
        <p className="text-sm text-muted-foreground">
          Re-ranks the library instantly from the stored sub-scores — nothing is regenerated.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {SCORE_DIMENSIONS.map((dimension) => {
          const value = weights[dimension] ?? DEFAULT_WEIGHT;
          return (
            <label key={dimension} className="block text-xs">
              <span className="flex items-center justify-between">
                {DIMENSION_LABELS[dimension]}
                <span className="font-medium tabular-nums" data-testid={`weight-value-${dimension}`}>
                  ×{value.toFixed(1)}
                </span>
              </span>
              <Slider
                aria-label={`${DIMENSION_LABELS[dimension]} weight`}
                data-testid={`weight-slider-${dimension}`}
                min={MIN_WEIGHT}
                max={MAX_WEIGHT}
                step={0.1}
                value={value}
                onValueChange={(next) => onWeightChange(dimension, next)}
              />
            </label>
          );
        })}
      </div>
      <div className="flex items-center gap-3">
        <Button size="sm" variant="outline" data-testid="weights-save" disabled={saving} onClick={onSave}>
          Save weights
        </Button>
        {saved && (
          <p className="text-xs text-muted-foreground" data-testid="weights-saved">
            Saved.
          </p>
        )}
        {saveError && (
          <p className="text-xs text-destructive" data-testid="weights-save-error">
            {saveError}
          </p>
        )}
      </div>
    </div>
  );
}
