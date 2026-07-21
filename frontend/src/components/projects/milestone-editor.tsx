"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  MILESTONE_STATUSES,
  createMilestone,
  deleteMilestone,
  reorderMilestones,
  updateMilestone,
  type MilestoneRead,
  type MilestoneStatus,
} from "@/lib/api";

export interface MilestoneEditorProps {
  projectId: number;
  milestones: MilestoneRead[];
}

/** Roadmap CRUD + up/down reorder (keyboard-accessible, no drag-drop). */
export function MilestoneEditor({ projectId, milestones }: MilestoneEditorProps) {
  const queryClient = useQueryClient();
  const [titleInput, setTitleInput] = useState("");

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["project", projectId] });
  };

  const create = useMutation({
    mutationFn: () => createMilestone(projectId, { title: titleInput.trim() }),
    onSuccess: async () => {
      setTitleInput("");
      await invalidate();
    },
  });

  const setStatus = useMutation({
    mutationFn: ({ milestoneId, status }: { milestoneId: number; status: MilestoneStatus }) =>
      updateMilestone(projectId, milestoneId, { status }),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (milestoneId: number) => deleteMilestone(projectId, milestoneId),
    onSuccess: invalidate,
  });

  const reorder = useMutation({
    mutationFn: (milestoneIds: number[]) => reorderMilestones(projectId, milestoneIds),
    onSuccess: invalidate,
  });

  function move(index: number, offset: -1 | 1) {
    const ids = milestones.map((milestone) => milestone.id);
    const target = index + offset;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    reorder.mutate(ids);
  }

  return (
    <section className="space-y-3 rounded-lg border bg-card p-4" data-testid="milestone-editor">
      <div>
        <p className="font-medium">Roadmap milestones</p>
        <p className="text-sm text-muted-foreground">
          Track the build order; reorder with the arrows.
        </p>
      </div>

      <ul className="space-y-2">
        {milestones.map((milestone, index) => (
          <li
            key={milestone.id}
            className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm"
            data-testid="milestone-row"
          >
            <span className="min-w-0 flex-1 truncate" data-testid="milestone-title">
              {milestone.title}
            </span>
            <select
              aria-label={`Status of ${milestone.title}`}
              data-testid="milestone-status"
              className="rounded-md border border-input bg-background px-2 py-1 text-xs"
              value={milestone.status}
              onChange={(event) =>
                setStatus.mutate({
                  milestoneId: milestone.id,
                  status: event.target.value as MilestoneStatus,
                })
              }
            >
              {MILESTONE_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Move ${milestone.title} up`}
              data-testid="milestone-up"
              disabled={index === 0 || reorder.isPending}
              onClick={() => move(index, -1)}
            >
              ↑
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Move ${milestone.title} down`}
              data-testid="milestone-down"
              disabled={index === milestones.length - 1 || reorder.isPending}
              onClick={() => move(index, 1)}
            >
              ↓
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Delete ${milestone.title}`}
              data-testid="milestone-delete"
              disabled={remove.isPending}
              onClick={() => remove.mutate(milestone.id)}
            >
              ✕
            </Button>
          </li>
        ))}
        {milestones.length === 0 && (
          <li className="text-sm text-muted-foreground" data-testid="milestones-empty">
            No milestones yet.
          </li>
        )}
      </ul>

      <div className="flex items-center gap-2">
        <Input
          aria-label="New milestone title"
          data-testid="milestone-title-input"
          className="max-w-sm"
          value={titleInput}
          onChange={(event) => setTitleInput(event.target.value)}
          placeholder="Add a milestone…"
        />
        <Button
          size="sm"
          data-testid="milestone-add"
          disabled={!titleInput.trim() || create.isPending}
          onClick={() => create.mutate()}
        >
          Add
        </Button>
      </div>
    </section>
  );
}
