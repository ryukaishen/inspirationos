import type { BadgeProps } from "@/components/ui/badge";
import type { ItemStatus, ItemType } from "@/lib/api";

export const TYPE_LABELS: Record<ItemType, string> = {
  reel: "Reel",
  post: "Post",
  tv: "TV",
  story: "Story",
  external: "External",
  unknown: "Unknown",
};

export const STATUS_LABELS: Record<ItemStatus, string> = {
  new: "New",
  needs_context: "Needs context",
  reviewed: "Reviewed",
  archived: "Archived",
  ignored: "Ignored",
};

export const STATUS_VARIANT: Record<ItemStatus, BadgeProps["variant"]> = {
  new: "secondary",
  needs_context: "destructive",
  reviewed: "success",
  archived: "muted",
  ignored: "outline",
};
