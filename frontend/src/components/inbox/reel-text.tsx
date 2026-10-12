import type { ItemRead } from "@/lib/api";

interface ReelTextSection {
  key: string;
  label: string;
  text: string;
}

function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

/**
 * Text extracted from the reel itself by the `transcribe-reels` CLI: the speech
 * transcript and on-screen text. Collapsed by default so long transcripts don't
 * swamp the inbox.
 */
export function ReelText({ item, defaultOpen = false }: { item: ItemRead; defaultOpen?: boolean }) {
  const sections: ReelTextSection[] = [];
  if (item.transcript?.trim()) {
    sections.push({ key: "transcript", label: "Transcript", text: item.transcript });
  }
  if (item.visual_text?.trim()) {
    sections.push({ key: "visual", label: "On-screen text", text: item.visual_text });
  }
  if (sections.length === 0) return null;

  return (
    <div className="space-y-1" data-testid="reel-text">
      {sections.map((section) => (
        <details key={section.key} open={defaultOpen} data-testid={`reel-${section.key}`}>
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            {section.label} ({wordCount(section.text)} words)
          </summary>
          <p className="mt-1 whitespace-pre-wrap">{section.text}</p>
        </details>
      ))}
    </div>
  );
}
