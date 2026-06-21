import Link from "next/link";
import { getDict } from "@/lib/i18n/server";
import { LoginForm } from "./login-form";

export default function LoginPage() {
  const t = getDict();
  return (
    <div className="bg-card rounded-xl shadow-sm border p-6">
      <h2 className="text-2xl font-bold mb-6">{t.auth.login}</h2>
      <LoginForm t={t.auth} />
      <p className="text-center mt-6">
        <Link href="/signup" className="text-primary font-medium underline">
          {t.auth.switchToSignup}
        </Link>
      </p>
    </div>
  );
}
