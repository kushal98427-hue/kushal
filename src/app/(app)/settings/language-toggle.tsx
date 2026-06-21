"use client";

import { useTransition } from "react";
import { setLanguage } from "@/actions/settings";
import { cn } from "@/lib/utils";
import type { Lang } from "@/lib/i18n/dict";

export function LanguageToggle({
  current,
  labels,
}: {
  current: Lang;
  labels: Record<Lang, string>;
}) {
  const [pending, start] = useTransition();
  const options: Lang[] = ["np", "en"];

  return (
    <div className="grid grid-cols-2 gap-2">
      {options.map((lang) => {
        const active = lang === current;
        return (
          <button
            key={lang}
            type="button"
            disabled={pending || active}
            onClick={() => start(() => setLanguage(lang))}
            className={cn(
              "h-14 rounded-md border-2 font-semibold text-lg",
              active
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-background border-input text-foreground",
            )}
          >
            {labels[lang]}
          </button>
        );
      })}
    </div>
  );
}
