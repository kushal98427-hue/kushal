# उधारो रजिस्टर — Udharo Register

A dead-simple udharo (credit) book for Nepali hardware, paint, sanitary, electrical, and building-material shops.

**v0.1 scope (this commit):** signup/login, customers, ledger entries (udharo + payment), per-customer balance, dashboard totals, Nepali/English UI, installable PWA. Nothing more — deliberately.

---

## Stack
- Next.js 14 (App Router) + TypeScript
- Tailwind CSS + custom shadcn-style components
- Supabase (Auth + Postgres + RLS)
- Hosting: Netlify

## Folder map
```
src/
  app/                  Next.js routes
    (auth)/             login + signup
    (app)/              dashboard, customers, settings (behind auth)
  components/ui/        Button, Input, Label, Card
  components/           BottomNav
  lib/
    supabase/           browser, server, middleware clients
    i18n/               dict (np/en) + server helper
    utils.ts            cn, money/date formatters, phone normalizer
  actions/              server actions (auth, customers, entries, settings)
  middleware.ts         redirects logged-out users to /login
supabase/migrations/    SQL schema + RLS
public/                 PWA manifest, service worker, icon
```

---

## One-time setup (do this once, ~5 minutes)

### 1. Run the SQL migration in Supabase
1. Open https://supabase.com/dashboard → your project → **SQL Editor**.
2. Paste the contents of `supabase/migrations/0001_initial.sql` and click **Run**.
3. This creates `customers`, `ledger_entries`, the `customer_balances` view, and RLS policies.

### 2. Enable phone + password auth
1. In Supabase Dashboard → **Authentication → Providers → Phone**: enable it.
2. **Important:** under Phone provider settings, **disable** "Confirm phone" (so signup auto-logs-in without SMS). We're not paying for SMS in MVP.
3. Auth → **URL Configuration** → add your Netlify URL (e.g. `https://udharo.netlify.app`) and custom domain to **Site URL** + **Redirect URLs**.

### 3. Local development
```bash
cp .env.example .env.local
# fill NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY
npm install
npm run dev
# open http://localhost:3000
```

### 4. Deploy to Netlify
1. Push this repo to GitHub (you're already doing this).
2. In Netlify → **Add new site → Import from Git** → pick the repo.
3. Build command: `npm run build` (auto-detected). Publish dir: `.next` (auto).
4. Add env vars in **Site settings → Environment variables**:
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
5. Deploy. Map your Namecheap domain in **Domain management**.

---

## Testing the MVP (5 min smoke test)

1. Open the site → land on `/login` → click "Create account".
2. Enter shop name, phone (e.g. `9851234567`), password (≥6 chars) → submit.
3. You land on `/dashboard` with empty state.
4. Tap **Customers** → **New customer** → add "Hari Hardware" with phone.
5. Open Hari → tap **New entry** → "Gave udharo" → amount 25000 → Save.
6. Balance shows **Rs 25,000** in red.
7. Add another entry → "Received payment" → 10000 → balance becomes **Rs 15,000**.
8. Go back to **Dashboard** → total receivable shows **Rs 15,000**.
9. Settings → switch language → UI flips to English (or Nepali).
10. On Android Chrome → menu → "Install app" → app appears on home screen.

---

## What's intentionally NOT in v0.1
- Inventory / products / sales
- AI chat entry
- Voice input
- SMS reminders
- OCR
- Reports beyond the dashboard total
- Offline writes
- Multi-shop / staff accounts

Each of these is a real Phase 2+ item. We add them **after** real shopkeepers use v0.1 and tell us what's broken — not before.

## Next steps after first deploy
1. Get this in front of **one** shopkeeper. Watch them use it. Don't help. Take notes.
2. Whatever they get stuck on → that's Phase 1.5.
3. Only after 5 shopkeepers use it weekly do we touch Phase 2 (inventory).

## Generating real PNG icons later
The PWA currently uses an SVG icon, which works on Chrome/Edge/Android. For iOS App Store-quality polish later, generate `icon-192.png` and `icon-512.png` from `public/icon.svg` (any online SVG-to-PNG tool, or `npx @vite-pwa/assets-generator`) and update `public/manifest.json`.
