import type { ImportVerificationReport } from "@/lib/api";

/**
 * Raw-vs-parsed counts, every scan-pass skip categorized, and a
 * duplicate-reason summary (M10) — so "how much of the export did we
 * actually use, and why not the rest" is always answerable, never silent.
 */
export function VerificationReport({ report }: { report: ImportVerificationReport }) {
  return (
    <div className="space-y-4 text-sm" data-testid="verification-report">
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span>Message JSON files (raw ZIP scan)</span>
          <span data-testid="verification-raw-entries" className="font-medium tabular-nums">
            {report.raw_message_json_entries}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>Recognized categories</span>
          <span data-testid="verification-matched-entries" className="font-medium tabular-nums">
            {report.matched_message_json_entries}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>Conversations found</span>
          <span data-testid="verification-conversations" className="font-medium tabular-nums">
            {report.conversations_found}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>Messages parsed</span>
          <span data-testid="verification-messages-parsed" className="font-medium tabular-nums">
            {report.messages_parsed}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>Messages skipped</span>
          <span data-testid="verification-messages-skipped" className="font-medium tabular-nums">
            {report.messages_skipped}
          </span>
        </div>
        {report.extracted_messages !== null && (
          <div className="flex items-center justify-between">
            <span>Extracted messages</span>
            <span data-testid="verification-extracted-messages" className="font-medium tabular-nums">
              {report.extracted_messages}
            </span>
          </div>
        )}
        {report.items_extracted !== null && (
          <div className="flex items-center justify-between">
            <span>Items extracted</span>
            <span data-testid="verification-items-extracted" className="font-medium tabular-nums">
              {report.items_extracted}
            </span>
          </div>
        )}
      </div>

      <div>
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          Every skip, categorized
        </h3>
        <ul className="mt-1 space-y-1" data-testid="verification-skip-breakdown">
          {report.skip_breakdown.map((row) => (
            <li key={row.category} data-testid={`verification-skip-${row.category}`}>
              <div className="flex items-center justify-between gap-2">
                <span>{row.category}</span>
                <span className="font-medium tabular-nums">{row.count}</span>
              </div>
              <p className="text-xs text-muted-foreground">{row.description}</p>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          Duplicate groups by reason
        </h3>
        {report.duplicate_summary.length === 0 ? (
          <p className="mt-1 text-xs text-muted-foreground">
            None yet — duplicate groups are built by the extract pass.
          </p>
        ) : (
          <ul className="mt-1 space-y-1" data-testid="verification-duplicate-summary">
            {report.duplicate_summary.map((row) => (
              <li
                key={row.reason}
                className="flex items-center justify-between gap-2"
                data-testid={`verification-duplicate-${row.reason}`}
              >
                <span>{row.reason}</span>
                <span className="font-medium tabular-nums">
                  {row.group_count} group{row.group_count === 1 ? "" : "s"} · {row.item_count} items
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-1 text-xs text-muted-foreground">
          Individual groups are visible in the Inbox as grouped cards.
        </p>
      </div>
    </div>
  );
}
