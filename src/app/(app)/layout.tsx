import { getDict } from "@/lib/i18n/server";
import { BottomNav } from "@/components/bottom-nav";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const t = getDict();
  return (
    <div className="min-h-screen bg-secondary pb-24">
      <div className="max-w-md mx-auto">{children}</div>
      <BottomNav t={t.nav} />
    </div>
  );
}
