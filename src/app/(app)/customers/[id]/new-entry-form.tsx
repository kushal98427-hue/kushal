"use client";

import { useFormState, useFormStatus } from "react-dom";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createEntry } from "@/actions/entries";
import { cn } from "@/lib/utils";
import type { Dict } from "@/lib/i18n/dict";

function Submit({ label }: { label: string }) {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" size="lg" className="w-full" disabled={pending}>
      {label}
    </Button>
  );
}

export function NewEntryForm({
  customerId,
  t,
}: {
  customerId: string;
  t: Dict;
}) {
  const [state, action] = useFormState(createEntry, undefined);
  const [kind, setKind] = useState<"udharo" | "payment">("udharo");
  const today = new Date().toISOString().slice(0, 10);

  return (
    <form action={action} className="space-y-4">
      <input type="hidden" name="customer_id" value={customerId} />
      <input type="hidden" name="kind" value={kind} />

      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => setKind("udharo")}
          className={cn(
            "h-14 rounded-md border-2 font-semibold text-lg",
            kind === "udharo"
              ? "bg-destructive text-destructive-foreground border-destructive"
              : "bg-background border-input text-foreground",
          )}
        >
          {t.entries.udharo}
        </button>
        <button
          type="button"
          onClick={() => setKind("payment")}
          className={cn(
            "h-14 rounded-md border-2 font-semibold text-lg",
            kind === "payment"
              ? "bg-primary text-primary-foreground border-primary"
              : "bg-background border-input text-foreground",
          )}
        >
          {t.entries.payment}
        </button>
      </div>

      <div className="space-y-2">
        <Label htmlFor="amount">
          {t.entries.amount} ({t.common.currency})
        </Label>
        <Input
          id="amount"
          name="amount"
          type="number"
          inputMode="decimal"
          step="0.01"
          min="0.01"
          required
          autoFocus
          className="text-2xl font-bold h-16"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="entry_date">{t.entries.date}</Label>
        <Input
          id="entry_date"
          name="entry_date"
          type="date"
          defaultValue={today}
          required
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="note">{t.entries.note}</Label>
        <Input id="note" name="note" maxLength={500} />
      </div>

      {state?.error && (
        <p className="text-destructive text-base">{t.auth.errorGeneric}</p>
      )}

      <Submit label={t.entries.save} />
    </form>
  );
}
