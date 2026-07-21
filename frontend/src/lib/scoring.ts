// Pure scoring math (M7) — mirrors backend services/generation/scoring.py.
// The weighted total is computed at read time from stored sub-scores, so
// changing weights re-ranks the library instantly with zero API calls.
// Framework-free like item-filters.ts / review-keyboard.ts; both sides share
// the same unit-test cases so the implementations cannot drift silently.

import type { SubScore } from "@/lib/api";

export const SCORE_DIMENSIONS = [
  "career_alignment",
  "technical_depth",
  "originality",
  "feasibility",
  "recruiter_appeal",
] as const;

export type ScoreDimension = (typeof SCORE_DIMENSIONS)[number];

export const DIMENSION_LABELS: Record<ScoreDimension, string> = {
  career_alignment: "Career alignment",
  technical_depth: "Technical depth",
  originality: "Originality",
  feasibility: "Feasibility",
  recruiter_appeal: "Recruiter appeal",
};

export const DEFAULT_WEIGHT = 1.0;
export const MIN_WEIGHT = 0.0;
export const MAX_WEIGHT = 2.0;

export type Weights = Record<string, number>;

export function computeScore(
  scores: Record<string, SubScore | undefined>,
  weights: Weights = {},
): number {
  let total = 0;
  for (const dimension of SCORE_DIMENSIONS) {
    const entry = scores[dimension];
    if (!entry || typeof entry.score !== "number" || Number.isNaN(entry.score)) continue;
    const weight =
      typeof weights[dimension] === "number" && !Number.isNaN(weights[dimension])
        ? weights[dimension]
        : DEFAULT_WEIGHT;
    total += weight * entry.score;
  }
  return Math.round(total * 100) / 100;
}

export interface Scoreable {
  id: number;
  scores: Record<string, SubScore | undefined>;
}

/** Score-descending order; ties break by id ascending so the sort is stable
 * across recomputes and the two implementations agree exactly. */
export function rankProjects<T extends Scoreable>(projects: readonly T[], weights: Weights = {}): T[] {
  return [...projects].sort(
    (a, b) => computeScore(b.scores, weights) - computeScore(a.scores, weights) || a.id - b.id,
  );
}
