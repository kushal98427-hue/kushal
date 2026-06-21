"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";
import { normalizePhone } from "@/lib/utils";

const phoneSchema = z.string().min(10).max(15);
const passwordSchema = z.string().min(6).max(72);

export type AuthState = { error?: string } | undefined;

export async function loginAction(
  _prev: AuthState,
  formData: FormData,
): Promise<AuthState> {
  const rawPhone = String(formData.get("phone") ?? "");
  const password = String(formData.get("password") ?? "");

  if (!phoneSchema.safeParse(rawPhone).success) return { error: "invalid" };
  if (!passwordSchema.safeParse(password).success) return { error: "invalid" };

  const supabase = createClient();
  const { error } = await supabase.auth.signInWithPassword({
    phone: normalizePhone(rawPhone),
    password,
  });

  if (error) return { error: "invalid" };

  revalidatePath("/", "layout");
  redirect("/dashboard");
}

export async function signupAction(
  _prev: AuthState,
  formData: FormData,
): Promise<AuthState> {
  const rawPhone = String(formData.get("phone") ?? "");
  const password = String(formData.get("password") ?? "");
  const shopName = String(formData.get("shop_name") ?? "").trim();

  if (!phoneSchema.safeParse(rawPhone).success) return { error: "invalid" };
  if (!passwordSchema.safeParse(password).success) return { error: "invalid" };
  if (!shopName) return { error: "invalid" };

  const supabase = createClient();
  const { error } = await supabase.auth.signUp({
    phone: normalizePhone(rawPhone),
    password,
    options: { data: { shop_name: shopName } },
  });

  if (error) return { error: "generic" };

  // Phone signup without SMS confirmation is auto-signed-in by Supabase
  // when SMS provider is disabled. If your project requires confirmation,
  // we'll switch to OTP flow later.
  revalidatePath("/", "layout");
  redirect("/dashboard");
}

export async function logoutAction(): Promise<void> {
  const supabase = createClient();
  await supabase.auth.signOut();
  redirect("/login");
}
