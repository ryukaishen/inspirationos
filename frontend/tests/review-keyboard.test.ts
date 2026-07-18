import { describe, expect, it } from "vitest";

import { mapKeyToAction } from "@/lib/review-keyboard";

describe("mapKeyToAction (not editing the note)", () => {
  it.each([
    ["j", { type: "next" }],
    ["k", { type: "prev" }],
    ["o", { type: "open" }],
    ["e", { type: "focus_note" }],
    ["s", { type: "skip" }],
    ["Enter", { type: "save_and_advance" }],
    ["1", { type: "set_status", status: "new" }],
    ["2", { type: "set_status", status: "needs_context" }],
    ["3", { type: "set_status", status: "reviewed" }],
    ["4", { type: "set_status", status: "archived" }],
    ["5", { type: "set_status", status: "ignored" }],
  ] as const)("maps %s to %o", (key, expected) => {
    expect(mapKeyToAction(key, false)).toEqual(expected);
  });

  it("ignores unmapped keys", () => {
    expect(mapKeyToAction("z", false)).toBeNull();
    expect(mapKeyToAction("6", false)).toBeNull();
    expect(mapKeyToAction("Escape", false)).toBeNull();
  });
});

describe("mapKeyToAction (editing the note)", () => {
  it("only intercepts Enter and Escape", () => {
    expect(mapKeyToAction("Enter", true)).toEqual({ type: "save_and_advance" });
    expect(mapKeyToAction("Escape", true)).toEqual({ type: "cancel_edit" });
  });

  it("lets every other key type normally", () => {
    for (const key of ["j", "k", "o", "e", "s", "1", "a", " "]) {
      expect(mapKeyToAction(key, true)).toBeNull();
    }
  });
});
