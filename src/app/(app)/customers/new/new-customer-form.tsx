"use client";

import { useFormState, useFormStatus } from "react-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createCustomer } from "@/actions/customers";
import type { Dict } from "@/lib/i18n/dict";

function Submit({ label, saving }: { label: string; saving: string }) {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" size="lg" className="w-full" disabled={pending}>
      {pending ? saving : label}
    </Button>
  );
}

export function NewCustomerForm({ t }: { t: Dict }) {
  const [state, action] = useFormState(createCustomer, undefined);
  return (
    <form action={action} className="space-y-5">
      <div className="space-y-2">
        <Label htmlFor="name">{t.customers.name}</Label>
        <Input id="name" name="name" required autoFocus maxLength={120} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="phone">{t.customers.phone}</Label>
        <Input
          id="phone"
          name="phone"
          type="tel"
          inputMode="numeric"
          maxLength={20}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="note">{t.customers.note}</Label>
        <Input id="note" name="note" maxLength={500} />
      </div>
      {state?.error && (
        <p className="text-destructive text-base">{t.auth.errorGeneric}</p>
      )}
      <Submit label={t.customers.save} saving={t.customers.saving} />
    </form>
  );
}
