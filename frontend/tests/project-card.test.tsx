import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProjectCard } from "@/components/projects/project-card";
import type { ProjectRead } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

function makeProject(overrides: Partial<ProjectRead> = {}): ProjectRead {
  return {
    id: 7,
    title: "Sourdough Sensor Dashboard",
    one_liner: "Track starter fermentation with cheap sensors.",
    summary_md: "## Summary",
    domains: ["data science"],
    difficulty: "intermediate",
    duration_estimate: "4-6 weeks",
    datasets: [],
    tech_stack: ["python"],
    skills_demonstrated: ["time series"],
    risks: [],
    scores: {
      career_alignment: { score: 8.0, rationale: "Fits the data-science target." },
      technical_depth: { score: 6.5, rationale: "Real pipeline, modest modeling." },
      originality: { score: 4.0, rationale: "Sensor dashboards are common." },
      feasibility: { score: 9.0, rationale: "Cheap hardware, small scope." },
      recruiter_appeal: { score: 5.5, rationale: "Concrete and demoable." },
    },
    status: "idea",
    source: { item_ids: [1, 2], cluster_ids: [3], provider: "mock", model: "mock-llm-v1" },
    parent_project_ids: [],
    created_at: "2026-07-19T00:00:00Z",
    updated_at: "2026-07-19T00:00:00Z",
    ...overrides,
  };
}

describe("ProjectCard", () => {
  it("renders sub-score bars with values and rationales plus the weighted total", () => {
    render(
      <ProjectCard
        project={makeProject()}
        weights={{}}
        selected={false}
        onToggleSelect={() => {}}
      />,
    );
    // 8 + 6.5 + 4 + 9 + 5.5 = 33.0 under default weights.
    expect(screen.getByTestId("project-score")).toHaveTextContent("33.0");
    expect(screen.getByTestId("score-value-career_alignment")).toHaveTextContent("8.0");
    expect(screen.getByTestId("score-rationale-career_alignment")).toHaveTextContent(
      "Fits the data-science target.",
    );
    expect(screen.getByTestId("score-rationale-originality")).toHaveTextContent(
      "Sensor dashboards are common.",
    );
    expect(screen.queryByTestId("project-combined-badge")).not.toBeInTheDocument();
  });

  it("applies weights to the total and marks combined projects", () => {
    render(
      <ProjectCard
        project={makeProject({ parent_project_ids: [1, 2] })}
        weights={{ feasibility: 2.0, originality: 0.0 }}
        selected={false}
        onToggleSelect={() => {}}
      />,
    );
    // 8 + 6.5 + 0 + 18 + 5.5 = 38.0.
    expect(screen.getByTestId("project-score")).toHaveTextContent("38.0");
    expect(screen.getByTestId("project-combined-badge")).toHaveTextContent("Combined");
  });
});
