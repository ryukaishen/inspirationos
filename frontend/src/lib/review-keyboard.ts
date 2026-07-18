// Pure keymap for the fast review mode — framework-free and independently
// unit-testable (mirrors item-filters.ts's pure-logic-first convention).
// The hook (use-review-keyboard.ts) only wires this to a keydown listener.

import { ITEM_STATUSES, type ItemStatus } from "@/lib/api";

export type ReviewAction =
  | { type: "next" }
  | { type: "prev" }
  | { type: "open" }
  | { type: "focus_note" }
  | { type: "save_and_advance" }
  | { type: "cancel_edit" }
  | { type: "skip" }
  | { type: "set_status"; status: ItemStatus };

/**
 * `isEditingNote` is true while the note textarea has focus: only Enter
 * (save + advance) and Escape (cancel) are intercepted then — every other
 * key types normally, so shortcuts never hijack note text. Notes are a
 * one-sentence field (see PRODUCT_SPEC.md), so Enter never needs to insert
 * a newline instead of saving.
 */
export function mapKeyToAction(key: string, isEditingNote: boolean): ReviewAction | null {
  if (isEditingNote) {
    if (key === "Enter") return { type: "save_and_advance" };
    if (key === "Escape") return { type: "cancel_edit" };
    return null;
  }

  switch (key) {
    case "j":
      return { type: "next" };
    case "k":
      return { type: "prev" };
    case "o":
      return { type: "open" };
    case "e":
      return { type: "focus_note" };
    case "s":
      return { type: "skip" };
    case "Enter":
      return { type: "save_and_advance" };
    case "1":
    case "2":
    case "3":
    case "4":
    case "5": {
      const status = ITEM_STATUSES[Number(key) - 1];
      return status ? { type: "set_status", status } : null;
    }
    default:
      return null;
  }
}
