"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";

const customerSchema = z.object({
  name: z.string().trim().min(1).max(120),
  phone: z.string().trim().max(20).optional().or(z.literal("")),
  note: z.string().trim().max(500).optional().or(z.literal("")),
});

export type CustomerState = { error?: string } | undefined;

export async function createCustomer(
  _prev: CustomerState,
  formData: FormData,
): Promise<CustomerState> {
  const parsed = customerSchema.safeParse({
    name: formData.get("name"),
    phone: formData.get("phone"),
    note: formData.get("note"),
  });
  if (!parsed.success) return { error: "invalid" };

  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  const { error } = await supabase.from("customers").insert({
    owner_id: user.id,
    name: parsed.data.name,
    phone: parsed.data.phone || null,
    note: parsed.data.note || null,
  });

  if (error) return { error: "generic" };

  revalidatePath("/customers");
  revalidatePath("/dashboard");
  redirect("/customers");
}
