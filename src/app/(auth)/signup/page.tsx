import Link from "next/link";
import { getDict } from "@/lib/i18n/server";
import { SignupForm } from "./signup-form";

export default function SignupPage() {
  const t = getDict();
  return (
    <div className="bg-card rounded-xl shadow-sm border p-6">
      <h2 className="text-2xl font-bold mb-6">{t.auth.signup}</h2>
      <SignupForm t={t.auth} />
      <p className="text-center mt-6">
        <Link href="/login" className="text-primary font-medium underline">
          {t.auth.switchToLogin}
        </Link>
      </p>
    </div>
  );
}
