import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { getDict } from "@/lib/i18n/server";
import { NewCustomerForm } from "./new-customer-form";

export default function NewCustomerPage() {
  const t = getDict();
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
        <h1 className="text-2xl font-bold mt-2">{t.customers.add}</h1>
      </header>
      <NewCustomerForm t={t} />
    </div>
  );
}
