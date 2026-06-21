"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { LANGS, type Lang } from "@/lib/i18n/dict";
import { LANG_COOKIE } from "@/lib/i18n/server";

export async function setLanguage(lang: Lang): Promise<void> {
  if (!LANGS.includes(lang)) return;
  cookies().set(LANG_COOKIE, lang, {
    httpOnly: false,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
  });
  revalidatePath("/", "layout");
}
