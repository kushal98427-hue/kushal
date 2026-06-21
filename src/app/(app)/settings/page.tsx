import { LogOut } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { getDict, getLang } from "@/lib/i18n/server";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { logoutAction } from "@/actions/auth";
import { LanguageToggle } from "./language-toggle";

export default async function SettingsPage() {
  const t = getDict();
  const lang = getLang();
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const shopName = (user?.user_metadata as { shop_name?: string } | undefined)
    ?.shop_name;

  return (
    <div className="p-4 space-y-5">
      <header className="pt-4">
        <h1 className="text-2xl font-bold">{t.settings.title}</h1>
      </header>

      <Card>
        <CardContent className="p-5 space-y-3">
          <p className="text-sm text-muted-foreground">{t.settings.account}</p>
          {shopName && <p className="font-semibold text-lg">{shopName}</p>}
          {user?.phone && <p className="text-muted-foreground">{user.phone}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-5 space-y-3">
          <p className="text-sm text-muted-foreground">{t.settings.language}</p>
          <LanguageToggle
            current={lang}
            labels={{ np: t.settings.nepali, en: t.settings.english }}
          />
        </CardContent>
      </Card>

      <form action={logoutAction}>
        <Button type="submit" variant="outline" size="lg" className="w-full">
          <LogOut className="w-5 h-5" />
          {t.auth.logout}
        </Button>
      </form>
    </div>
  );
}
