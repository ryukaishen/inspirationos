import type { SubScore } from "@/lib/api";
import { DIMENSION_LABELS, SCORE_DIMENSIONS } from "@/lib/scoring";

/** Transparent scoring: one bar + one-line rationale per dimension. */
export function ScoreBars({ scores }: { scores: Record<string, SubScore | undefined> }) {
  return (
    <div className="space-y-2" data-testid="score-bars">
      {SCORE_DIMENSIONS.map((dimension) => {
        const entry = scores[dimension];
        if (!entry) return null;
        return (
          <div key={dimension} className="space-y-0.5" data-testid={`score-${dimension}`}>
            <div className="flex items-center justify-between gap-2 text-xs">
              <span>{DIMENSION_LABELS[dimension]}</span>
              <span className="font-medium tabular-nums" data-testid={`score-value-${dimension}`}>
                {entry.score.toFixed(1)}
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary"
                style={{ width: `${Math.min(100, Math.max(0, (entry.score / 10) * 100))}%` }}
              />
            </div>
            <p
              className="text-xs text-muted-foreground"
              data-testid={`score-rationale-${dimension}`}
            >
              {entry.rationale}
            </p>
          </div>
        );
      })}
    </div>
  );
}
