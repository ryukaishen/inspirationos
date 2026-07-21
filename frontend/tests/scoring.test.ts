// Mirrors backend/tests/unit/test_scoring.py — the same cases with the same
// expected numbers, so the two compute_score implementations cannot drift.

import { describe, expect, it } from "vitest";

import type { SubScore } from "@/lib/api";
import { computeScore, DEFAULT_WEIGHT, rankProjects, SCORE_DIMENSIONS } from "@/lib/scoring";

function scores(values: Record<string, number>): Record<string, SubScore> {
  return Object.fromEntries(
    Object.entries(values).map(([dimension, score]) => [
      dimension,
      { score, rationale: `because ${dimension}` },
    ]),
  );
}

const FULL_SCORES = scores({
  career_alignment: 8,
  technical_depth: 6,
  originality: 4,
  feasibility: 9,
  recruiter_appeal: 5,
});

describe("computeScore", () => {
  it("has five dimensions and a default weight of 1", () => {
    expect(SCORE_DIMENSIONS).toHaveLength(5);
    expect(DEFAULT_WEIGHT).toBe(1.0);
  });

  it("sums all dimensions under default weights", () => {
    expect(computeScore(FULL_SCORES)).toBe(32.0);
  });

  it("applies weight overrides", () => {
    // 8 + 6 + (2 * 4) + (0 * 9) + 5 — same case as the backend test.
    expect(computeScore(FULL_SCORES, { originality: 2.0, feasibility: 0.0 })).toBe(27.0);
  });

  it("skips missing dimensions instead of crashing", () => {
    expect(computeScore(scores({ career_alignment: 7 }))).toBe(7.0);
    expect(computeScore({})).toBe(0.0);
  });

  it("ignores malformed stored entries", () => {
    const malformed = {
      career_alignment: { score: "high", rationale: "not numeric" },
      technical_depth: "not an object",
      originality: { rationale: "score missing" },
      recruiter_appeal: { score: 6, rationale: "fine" },
    } as unknown as Record<string, SubScore>;
    expect(computeScore(malformed)).toBe(6.0);
  });
});

describe("rankProjects", () => {
  const deep = {
    id: 1,
    scores: scores({
      career_alignment: 5,
      technical_depth: 9,
      originality: 5,
      feasibility: 4,
      recruiter_appeal: 5,
    }),
  };
  const safe = {
    id: 2,
    scores: scores({
      career_alignment: 5,
      technical_depth: 4,
      originality: 5,
      feasibility: 9,
      recruiter_appeal: 5,
    }),
  };

  it("re-orders under different weights (tied by default)", () => {
    expect(computeScore(deep.scores)).toBe(computeScore(safe.scores));
    const feasibilityFirst = { feasibility: 2.0, technical_depth: 0.5 };
    const depthFirst = { technical_depth: 2.0, feasibility: 0.5 };
    expect(rankProjects([deep, safe], feasibilityFirst).map((p) => p.id)).toEqual([2, 1]);
    expect(rankProjects([deep, safe], depthFirst).map((p) => p.id)).toEqual([1, 2]);
  });

  it("breaks ties by id and does not mutate the input", () => {
    const input = [safe, deep];
    expect(rankProjects(input).map((p) => p.id)).toEqual([1, 2]);
    expect(input.map((p) => p.id)).toEqual([2, 1]);
  });
});
