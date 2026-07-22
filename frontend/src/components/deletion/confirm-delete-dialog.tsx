"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

interface ConfirmDeleteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: React.ReactNode;
  /** The exact string the user must retype — a filename, project title, or
   * account email, matching the backend's typed-confirmation check. */
  confirmValue: string;
  confirmLabel?: string;
  onConfirm: () => void;
  isPending?: boolean;
  error?: string | null;
  testIdPrefix: string;
  children?: React.ReactNode;
}

export function ConfirmDeleteDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmValue,
  confirmLabel = "Delete",
  onConfirm,
  isPending = false,
  error = null,
  testIdPrefix,
  children,
}: ConfirmDeleteDialogProps) {
  const [typed, setTyped] = useState("");
  const matches = typed.length > 0 && typed === confirmValue;

  function handleOpenChange(next: boolean) {
    onOpenChange(next);
    if (!next) setTyped("");
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>
      <div className="space-y-3">
        <label className="block text-sm">
          Type <span className="font-mono font-medium">{confirmValue}</span> to confirm
          <Input
            className="mt-1"
            data-testid={`${testIdPrefix}-confirm-input`}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            autoComplete="off"
          />
        </label>
        {children}
        {error && (
          <p className="text-xs text-destructive" data-testid={`${testIdPrefix}-error`}>
            {error}
          </p>
        )}
      </div>
      <DialogFooter>
        <Button
          variant="ghost"
          data-testid={`${testIdPrefix}-cancel`}
          onClick={() => handleOpenChange(false)}
        >
          Cancel
        </Button>
        <Button
          variant="destructive"
          data-testid={`${testIdPrefix}-confirm`}
          disabled={!matches || isPending}
          onClick={onConfirm}
        >
          {isPending ? "Working…" : confirmLabel}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
