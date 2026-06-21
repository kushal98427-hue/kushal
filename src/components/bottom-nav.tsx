"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Users, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Dict } from "@/lib/i18n/dict";

type Item = { href: string; label: string; icon: typeof Users };

export function BottomNav({ t }: { t: Dict["nav"] }) {
  const pathname = usePathname();
  const items: Item[] = [
    { href: "/dashboard", label: t.dashboard, icon: LayoutDashboard },
    { href: "/customers", label: t.customers, icon: Users },
    { href: "/settings", label: t.settings, icon: Settings },
  ];

  return (
    <nav className="fixed bottom-0 inset-x-0 z-30 bg-card border-t shadow-[0_-2px_8px_rgba(0,0,0,0.04)] pb-[env(safe-area-inset-bottom)]">
      <ul className="grid grid-cols-3 max-w-md mx-auto">
        {items.map(({ href, label, icon: Icon }) => {
          const active =
            pathname === href || (href !== "/" && pathname.startsWith(href));
          return (
            <li key={href}>
              <Link
                href={href}
                className={cn(
                  "flex flex-col items-center justify-center py-3 gap-1 text-sm font-medium",
                  active ? "text-primary" : "text-muted-foreground",
                )}
              >
                <Icon className="w-6 h-6" strokeWidth={active ? 2.5 : 2} />
                <span>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
