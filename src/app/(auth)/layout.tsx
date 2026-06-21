import { getDict } from "@/lib/i18n/server";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const t = getDict();
  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 py-8 bg-secondary">
      <div className="w-full max-w-md">
        <header className="text-center mb-8">
          <h1 className="text-3xl font-bold text-primary">{t.appName}</h1>
          <p className="text-muted-foreground mt-2">{t.tagline}</p>
        </header>
        {children}
      </div>
    </main>
  );
}
