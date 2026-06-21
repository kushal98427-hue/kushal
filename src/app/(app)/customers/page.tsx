import Link from "next/link";
import { Plus, ChevronRight } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { getDict } from "@/lib/i18n/server";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { formatMoney } from "@/lib/utils";
import { CustomerSearch } from "./customer-search";

export default async function CustomersPage({
  searchParams,
}: {
  searchParams: { q?: string };
}) {
  const t = getDict();
  const supabase = createClient();
  const q = (searchParams.q ?? "").trim();

  let query = supabase
    .from("customer_balances")
    .select("customer_id, name, phone, balance, last_entry_date")
    .order("balance", { ascending: false });

  if (q) query = query.ilike("name", `%${q}%`);

  const { data: rows } = await query;

  return (
    <div className="p-4 space-y-4">
      <header className="pt-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t.customers.title}</h1>
        <Button asChild size="sm">
          <Link href="/customers/new">
            <Plus className="w-5 h-5" />
            {t.customers.add}
          </Link>
        </Button>
      </header>

      <CustomerSearch placeholder={t.customers.search} defaultValue={q} />

      {!rows || rows.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-muted-foreground">
            {t.customers.none}
          </CardContent>
        </Card>
      ) : (
        <ul className="space-y-2">
          {rows.map((c) => {
            const bal = Number(c.balance ?? 0);
            return (
              <li key={c.customer_id}>
                <Link
                  href={`/customers/${c.customer_id}`}
                  className="flex items-center justify-between bg-card border rounded-xl px-4 py-4 active:bg-accent"
                >
                  <div className="min-w-0">
                    <p className="font-semibold text-lg truncate">{c.name}</p>
                    {c.phone && (
                      <p className="text-sm text-muted-foreground">{c.phone}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <div className="text-right">
                      <p
                        className={
                          bal > 0
                            ? "text-destructive font-bold text-lg"
                            : bal < 0
                              ? "text-primary font-bold text-lg"
                              : "text-muted-foreground font-bold text-lg"
                        }
                      >
                        {t.common.currency} {formatMoney(Math.abs(bal))}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {t.customers.balance}
                      </p>
                    </div>
                    <ChevronRight className="w-5 h-5 text-muted-foreground" />
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
