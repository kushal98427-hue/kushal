"use client";

import { useFormState, useFormStatus } from "react-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { signupAction } from "@/actions/auth";
import type { Dict } from "@/lib/i18n/dict";

function SubmitButton({ label }: { label: string }) {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" size="lg" className="w-full" disabled={pending}>
      {label}
    </Button>
  );
}

export function SignupForm({ t }: { t: Dict["auth"] }) {
  const [state, action] = useFormState(signupAction, undefined);

  return (
    <form action={action} className="space-y-5">
      <div className="space-y-2">
        <Label htmlFor="shop_name">{t.shopName}</Label>
        <Input id="shop_name" name="shop_name" type="text" required maxLength={120} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="phone">{t.phone}</Label>
        <Input
          id="phone"
          name="phone"
          type="tel"
          inputMode="numeric"
          autoComplete="tel"
          placeholder={t.phoneHint}
          required
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="password">{t.password}</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="new-password"
          placeholder={t.passwordHint}
          required
          minLength={6}
        />
      </div>
      {state?.error === "invalid" && (
        <p className="text-destructive text-base">{t.errorInvalid}</p>
      )}
      {state?.error === "generic" && (
        <p className="text-destructive text-base">{t.errorGeneric}</p>
      )}
      <SubmitButton label={t.submitSignup} />
    </form>
  );
}
