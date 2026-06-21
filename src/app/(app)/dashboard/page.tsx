import Link from "next/link";
import { Users, Plus } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { getDict } from "@/lib/i18n/server";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { formatMoney, formatDate } from "@/lib/utils";

export default async function DashboardPage() {
  const t = getDict();
  const supabase = createClient();

  const [{ data: balances }, { data: recent }] = await Promise.all([
    supabase
      .from("customer_balances")
      .select("customer_id, name, balance")
      .gt("balance", 0),
    supabase
      .from("ledger_entries")
      .select("id, kind, amount, entry_date, customer_id, customers(name)")
      .order("created_at", { ascending: false })
      .limit(8),
  ]);

  const totalReceivable = (balances ?? []).reduce(
    (s, r) => s + Number(r.balance ?? 0),
    0,
  );
  const customerCount = balances?.length ?? 0;

  return (
    <div className="p-4 space-y-5">
      <header className="pt-4">
        <h1 className="text-2xl font-bold">{t.dashboard.title}</h1>
      </header>

      <Card className="bg-primary text-primary-foreground border-0">
        <CardContent className="p-6">
          <p className="text-base opacity-90">{t.dashboard.totalReceivable}</p>
          <p className="text-4xl font-bold mt-2">
            {t.common.currency} {formatMoney(totalReceivable)}
          </p>
          <p className="text-sm opacity-90 mt-3">
            {customerCount} {t.dashboard.customers}
          </p>
        </CardContent>
      </Card>

      <div>
        <h2 className="text-xl font-semibold mb-3">{t.dashboard.recentActivity}</h2>
        {!recent || recent.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-center space-y-4">
              <Users className="w-12 h-12 mx-auto text-muted-foreground" />
              <p className="text-muted-foreground">{t.dashboard.noEntriesYet}</p>
              <Button asChild>
                <Link href="/customers/new">
                  <Plus className="w-5 h-5" />
                  {t.dashboard.addFirstCustomer}
                </Link>
              </Button>
            </CardContent>
          </Card>
        ) : (
          <ul className="space-y-2">
            {recent.map((e) => {
              const isUdharo = e.kind === "udharo";
              const customerName =
                (e.customers as { name?: string } | null)?.name ?? "";
              return (
                <li key={e.id}>
                  <Link
                    href={`/customers/${e.customer_id}`}
                    className="block bg-card border rounded-xl px-4 py-3 active:bg-accent"
                  >
                    <div className="flex justify-between items-start gap-3">
                      <div className="min-w-0">
                        <p className="font-semibold truncate">{customerName}</p>
                        <p className="text-sm text-muted-foreground">
                          {isUdharo ? t.customers.due : t.customers.paid} ·{" "}
                          {formatDate(e.entry_date)}
                        </p>
                      </div>
                      <p
                        className={
                          isUdharo
                            ? "text-destructive font-bold text-lg whitespace-nowrap"
                            : "text-primary font-bold text-lg whitespace-nowrap"
                        }
                      >
                        {isUdharo ? "+" : "−"}
                        {formatMoney(Number(e.amount))}
                      </p>
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
