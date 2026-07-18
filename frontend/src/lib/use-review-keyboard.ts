"use client";

import { useEffect } from "react";

import { mapKeyToAction, type ReviewAction } from "@/lib/review-keyboard";

export interface UseReviewKeyboardOptions {
  isEditingNote: boolean;
  onAction: (action: ReviewAction) => void;
  enabled?: boolean;
}

/** Wires the pure `mapKeyToAction` keymap to a window keydown listener. */
export function useReviewKeyboard({
  isEditingNote,
  onAction,
  enabled = true,
}: UseReviewKeyboardOptions): void {
  useEffect(() => {
    if (!enabled) return;

    function handleKeyDown(event: KeyboardEvent) {
      // Let browser/OS shortcuts (Cmd+K, etc.) pass through untouched.
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const action = mapKeyToAction(event.key, isEditingNote);
      if (action) {
        event.preventDefault();
        onAction(action);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isEditingNote, onAction, enabled]);
}
