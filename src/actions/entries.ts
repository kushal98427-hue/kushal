"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";

const entrySchema = z.object({
  customer_id: z.string().uuid(),
  kind: z.enum(["udharo", "payment"]),
  amount: z.coerce.number().positive().max(1_000_000_000),
  entry_date: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/)
    .optional()
    .or(z.literal("")),
  note: z.string().trim().max(500).optional().or(z.literal("")),
});

export type EntryState = { error?: string } | undefined;

export async function createEntry(
  _prev: EntryState,
  formData: FormData,
): Promise<EntryState> {
  const parsed = entrySchema.safeParse({
    customer_id: formData.get("customer_id"),
    kind: formData.get("kind"),
    amount: formData.get("amount"),
    entry_date: formData.get("entry_date"),
    note: formData.get("note"),
  });
  if (!parsed.success) return { error: "invalid" };

  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  const { error } = await supabase.from("ledger_entries").insert({
    owner_id: user.id,
    customer_id: parsed.data.customer_id,
    kind: parsed.data.kind,
    amount: parsed.data.amount,
    entry_date: parsed.data.entry_date || new Date().toISOString().slice(0, 10),
    note: parsed.data.note || null,
  });

  if (error) return { error: "generic" };

  revalidatePath(`/customers/${parsed.data.customer_id}`);
  revalidatePath("/customers");
  revalidatePath("/dashboard");
  redirect(`/customers/${parsed.data.customer_id}`);
}

export async function deleteEntry(id: string, customerId: string): Promise<void> {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  await supabase.from("ledger_entries").delete().eq("id", id);

  revalidatePath(`/customers/${customerId}`);
  revalidatePath("/customers");
  revalidatePath("/dashboard");
}
