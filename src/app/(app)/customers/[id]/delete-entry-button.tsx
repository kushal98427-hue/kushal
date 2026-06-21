"use client";

import { useTransition } from "react";
import { Trash2 } from "lucide-react";
import { deleteEntry } from "@/actions/entries";

export function DeleteEntryButton({
  entryId,
  customerId,
  confirmLabel,
  deleteLabel,
}: {
  entryId: string;
  customerId: string;
  confirmLabel: string;
  deleteLabel: string;
}) {
  const [pending, start] = useTransition();
  return (
    <button
      type="button"
      aria-label={deleteLabel}
      disabled={pending}
      onClick={() => {
        if (window.confirm(confirmLabel)) {
          start(() => deleteEntry(entryId, customerId));
        }
      }}
      className="text-muted-foreground hover:text-destructive disabled:opacity-40 p-1"
    >
      <Trash2 className="w-5 h-5" />
    </button>
  );
}
