import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WeightSliders } from "@/components/projects/weight-sliders";
import type { SubScore } from "@/lib/api";
import { rankProjects, type ScoreDimension, type Weights } from "@/lib/scoring";

function scores(values: Record<string, number>): Record<string, SubScore> {
  return Object.fromEntries(
    Object.entries(values).map(([dimension, score]) => [
      dimension,
      { score, rationale: `because ${dimension}` },
    ]),
  );
}

const DEEP = {
  id: 1,
  title: "Deep Project",
  scores: scores({
    career_alignment: 5,
    technical_depth: 9,
    originality: 5,
    feasibility: 4,
    recruiter_appeal: 5,
  }),
};
const SAFE = {
  id: 2,
  title: "Safe Project",
  scores: scores({
    career_alignment: 5,
    technical_depth: 4,
    originality: 5,
    feasibility: 9,
    recruiter_appeal: 5,
  }),
};

/** Page-shaped harness: sliders drive a useState that re-ranks a list. */
function Harness() {
  const [weights, setWeights] = useState<Weights>({});
  const ranked = rankProjects([DEEP, SAFE], weights);
  return (
    <div>
      <ol data-testid="ranked-titles">
        {ranked.map((project) => (
          <li key={project.id}>{project.title}</li>
        ))}
      </ol>
      <WeightSliders
        weights={weights}
        onWeightChange={(dimension: ScoreDimension, value: number) =>
          setWeights((current) => ({ ...current, [dimension]: value }))
        }
        onSave={() => {}}
        saving={false}
        saved={false}
        saveError={null}
      />
    </div>
  );
}

describe("WeightSliders", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("re-ranks the list instantly with no network request", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<Harness />);

    const titles = () =>
      [...screen.getByTestId("ranked-titles").querySelectorAll("li")].map(
        (node) => node.textContent,
      );
    // Tied under default weights -> id order.
    expect(titles()).toEqual(["Deep Project", "Safe Project"]);

    fireEvent.change(screen.getByTestId("weight-slider-feasibility"), {
      target: { value: "2" },
    });
    expect(titles()).toEqual(["Safe Project", "Deep Project"]);
    expect(screen.getByTestId("weight-value-feasibility")).toHaveTextContent("×2.0");

    fireEvent.change(screen.getByTestId("weight-slider-technical_depth"), {
      target: { value: "2" },
    });
    fireEvent.change(screen.getByTestId("weight-slider-feasibility"), {
      target: { value: "0.5" },
    });
    expect(titles()).toEqual(["Deep Project", "Safe Project"]);

    // The whole re-rank is client-side math — zero API calls.
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("renders one slider per dimension with the default weight", () => {
    render(<Harness />);
    for (const dimension of [
      "career_alignment",
      "technical_depth",
      "originality",
      "feasibility",
      "recruiter_appeal",
    ]) {
      expect(screen.getByTestId(`weight-slider-${dimension}`)).toBeInTheDocument();
      expect(screen.getByTestId(`weight-value-${dimension}`)).toHaveTextContent("×1.0");
    }
  });
});
