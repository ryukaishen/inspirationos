"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
  className?: string;
}

/**
 * Wraps the native <dialog> element for real focus-trap/Escape/backdrop
 * semantics without a Radix dependency — matching this project's other
 * hand-rolled UI primitives (checkbox/input/textarea). Mounted only while
 * `open` (rather than always-mounted + toggling the `open` attribute), so
 * its content's DOM presence is a reliable, directly testable signal.
 */
function Dialog({ open, onOpenChange, children, className }: DialogProps) {
  const ref = React.useRef<HTMLDialogElement>(null);

  // `Dialog` itself is always mounted by its parent (only its *content*
  // conditionally renders below); a []-deps effect would only ever see the
  // ref while it was still null on that first, closed render. Depending on
  // `open` re-fires it exactly when the <dialog> DOM node actually exists.
  React.useEffect(() => {
    // jsdom (unit tests) doesn't implement showModal(); guard so tests can
    // assert on the dialog's DOM presence without needing a real browser.
    if (open && typeof ref.current?.showModal === "function") {
      ref.current.showModal();
    }
  }, [open]);

  if (!open) return null;

  return (
    <dialog
      ref={ref}
      onClose={() => onOpenChange(false)}
      className={cn(
        "w-full max-w-md rounded-lg border bg-background p-6 text-foreground shadow-lg backdrop:bg-black/50",
        className,
      )}
    >
      {children}
    </dialog>
  );
}

function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mb-4 space-y-1", className)} {...props} />;
}

function DialogTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("text-lg font-semibold", className)} {...props} />;
}

function DialogDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...props} />;
}

function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mt-6 flex justify-end gap-2", className)} {...props} />;
}

export { Dialog, DialogDescription, DialogFooter, DialogHeader, DialogTitle };
