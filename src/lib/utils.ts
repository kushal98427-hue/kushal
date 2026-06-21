import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const NPR = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 0,
});

export function formatMoney(amount: number | string): string {
  const n = typeof amount === "string" ? Number(amount) : amount;
  if (!Number.isFinite(n)) return "0";
  return NPR.format(n);
}

export function formatDate(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

// Normalize a Nepali phone number for use as Supabase phone identifier.
// Supabase expects E.164 like +9779851234567.
export function normalizePhone(raw: string): string {
  const digits = raw.replace(/\D/g, "");
  if (digits.startsWith("977")) return `+${digits}`;
  if (digits.length === 10) return `+977${digits}`;
  return `+${digits}`;
}
