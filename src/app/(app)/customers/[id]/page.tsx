import Link from "next/link";
import { notFound } from "next/navigation";
import { ChevronLeft, Phone, Plus } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { getDict } from "@/lib/i18n/server";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { formatMoney, formatDate } from "@/lib/utils";
import { NewEntryForm } from "./new-entry-form";
import { DeleteEntryButton } from "./delete-entry-button";

export default async function CustomerDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const t = getDict();
  const supabase = createClient();

  const [{ data: customer }, { data: entries }, { data: balanceRow }] =
    await Promise.all([
      supabase
        .from("customers")
        .select("id, name, phone, note")
        .eq("id", params.id)
        .single(),
      supabase
        .from("ledger_entries")
        .select("id, kind, amount, note, entry_date, created_at")
        .eq("customer_id", params.id)
        .order("entry_date", { ascending: false })
        .order("created_at", { ascending: false }),
      supabase
        .from("customer_balances")
        .select("balance")
        .eq("customer_id", params.id)
        .single(),
    ]);

  if (!customer) notFound();

  const balance = Number(balanceRow?.balance ?? 0);

  return (
    <div className="p-4 space-y-5">
      <header className="pt-4">
        <Link
          href="/customers"
          className="inline-flex items-center text-muted-foreground"
        >
          <ChevronLeft className="w-5 h-5" />
          {t.common.back}
        </Link>
        <h1 className="text-2xl font-bold mt-2">{customer.name}</h1>
        {customer.phone && (
          <a
            href={`tel:${customer.phone}`}
            className="inline-flex items-center gap-2 text-primary mt-1"
          >
            <Phone className="w-4 h-4" />
            {customer.phone}
          </a>
        )}
      </header>

      <Card
        className={
          balance > 0
            ? "bg-destructive text-destructive-foreground border-0"
            : "bg-primary text-primary-foreground border-0"
        }
      >
        <CardContent className="p-6 text-center">
          <p className="text-base opacity-90">{t.customers.balance}</p>
          <p className="text-4xl font-bold mt-2">
            {t.common.currency} {formatMoney(Math.abs(balance))}
          </p>
          <p className="text-sm opacity-90 mt-2">
            {balance > 0 ? t.customers.due : balance < 0 ? t.customers.paid : ""}
          </p>
        </CardContent>
      </Card>

      <details className="bg-card rounded-xl border">
        <summary className="cursor-pointer p-4 font-semibold flex items-center gap-2">
          <Plus className="w-5 h-5 text-primary" />
          {t.entries.add}
        </summary>
        <div className="p-4 pt-0">
          <NewEntryForm customerId={customer.id} t={t} />
        </div>
      </details>

      <div>
        {!entries || entries.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-center text-muted-foreground">
              {t.customers.noEntries}
            </CardContent>
          </Card>
        ) : (
          <ul className="space-y-2">
            {entries.map((e) => {
              const isUdharo = e.kind === "udharo";
              return (
                <li
                  key={e.id}
                  className="bg-card border rounded-xl px-4 py-3 flex justify-between items-start gap-3"
                >
                  <div className="min-w-0">
                    <p className="font-semibold">
                      {isUdharo ? t.customers.due : t.customers.paid}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {formatDate(e.entry_date)}
                    </p>
                    {e.note && (
                      <p className="text-sm mt-1 text-muted-foreground">
                        {e.note}
                      </p>
                    )}
                  </div>
                  <div className="flex flex-col items-end gap-2 shrink-0">
                    <p
                      className={
                        isUdharo
                          ? "text-destructive font-bold text-lg"
                          : "text-primary font-bold text-lg"
                      }
                    >
                      {isUdharo ? "+" : "−"}
                      {formatMoney(Number(e.amount))}
                    </p>
                    <DeleteEntryButton
                      entryId={e.id}
                      customerId={customer.id}
                      confirmLabel={t.entries.confirmDelete}
                      deleteLabel={t.entries.delete}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
