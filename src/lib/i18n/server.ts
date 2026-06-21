import { cookies } from "next/headers";
import { dict, DEFAULT_LANG, LANGS, type Lang, type Dict } from "./dict";

export const LANG_COOKIE = "udharo_lang";

export function getLang(): Lang {
  const value = cookies().get(LANG_COOKIE)?.value as Lang | undefined;
  return value && LANGS.includes(value) ? value : DEFAULT_LANG;
}

export function getDict(): Dict {
  return dict[getLang()];
}
