-- AI Udharo Register: initial schema
-- Two tables: customers and ledger_entries. Each row scoped to the owning user via RLS.

create extension if not exists "pgcrypto";

-- Customers belong to one shop owner (auth.users.id).
create table public.customers (
  id          uuid primary key default gen_random_uuid(),
  owner_id    uuid not null references auth.users(id) on delete cascade,
  name        text not null,
  phone       text,
  note        text,
  created_at  timestamptz not null default now()
);

create index customers_owner_idx on public.customers(owner_id);
create index customers_owner_name_idx on public.customers(owner_id, lower(name));

-- Ledger entries: either udharo (credit given, amount positive)
-- or bhuktani (payment received, amount positive but kind='payment').
create type entry_kind as enum ('udharo', 'payment');

create table public.ledger_entries (
  id           uuid primary key default gen_random_uuid(),
  owner_id     uuid not null references auth.users(id) on delete cascade,
  customer_id  uuid not null references public.customers(id) on delete cascade,
  kind         entry_kind not null,
  amount       numeric(12,2) not null check (amount > 0),
  note         text,
  entry_date   date not null default current_date,
  created_at   timestamptz not null default now()
);

create index ledger_owner_idx on public.ledger_entries(owner_id);
create index ledger_customer_idx on public.ledger_entries(customer_id, entry_date desc);

-- Row Level Security: a user can only see and write their own rows.
alter table public.customers enable row level security;
alter table public.ledger_entries enable row level security;

create policy "customers_owner_all"
  on public.customers
  for all
  to authenticated
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

create policy "ledger_owner_all"
  on public.ledger_entries
  for all
  to authenticated
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

-- View: balance per customer (sum of udharo minus sum of payments).
create or replace view public.customer_balances
with (security_invoker = true)
as
select
  c.id            as customer_id,
  c.owner_id      as owner_id,
  c.name          as name,
  c.phone         as phone,
  coalesce(sum(case when e.kind = 'udharo'  then e.amount else 0 end), 0)
    - coalesce(sum(case when e.kind = 'payment' then e.amount else 0 end), 0)
                  as balance,
  max(e.entry_date) as last_entry_date
from public.customers c
left join public.ledger_entries e on e.customer_id = c.id
group by c.id, c.owner_id, c.name, c.phone;
