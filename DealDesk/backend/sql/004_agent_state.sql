-- DealDesk: what the agent needs to remember about each vendor. Paste into the Supabase SQL editor and run it.
-- Safe to run more than once. It only ADDS columns and widens one check, so nothing existing breaks.

alter table deals add column if not exists tactics jsonb;           -- the buyer-approved negotiation tactics
alter table deals add column if not exists max_rounds int;          -- null means "use the server setting"
alter table deals add column if not exists ceiling_ratio numeric;   -- null means "use the server setting"

alter table vendors add column if not exists stop_reason text;      -- why the agent stopped texting (firm_price, round_limit ...)
alter table vendors add column if not exists offers_so_far numeric[] not null default '{}';
alter table vendors add column if not exists firm boolean not null default false;      -- the vendor said the price is final
alter table vendors add column if not exists firm_pushes int not null default 0;       -- extra tries after "final price"
alter table vendors add column if not exists last_leverage numeric; -- the competing price we already told this vendor

-- "paused" = the agent stopped texting but the chat stays open
alter table vendors drop constraint if exists vendors_status_check;
alter table vendors add constraint vendors_status_check
  check (status in ('sent', 'replied', 'negotiating', 'paused', 'needs_you', 'closed', 'blocked'));

-- who writes this vendor's messages: a fake vendor ('simulator') or the person using the app ('you')
alter table vendors add column if not exists played_by text not null default 'simulator';
alter table vendors drop constraint if exists vendors_played_by_check;
alter table vendors add constraint vendors_played_by_check check (played_by in ('simulator', 'you'));

-- the user's final decision
alter table deals add column if not exists accepted_vendor_id uuid;
alter table deals add column if not exists accepted_price numeric;

-- variants (color, size, storage) and free extras (charger, hands-free ...)
alter table deals add column if not exists variant text not null default '';
alter table deals add column if not exists alt_variants text[] not null default '{}';
alter table deals add column if not exists addon_values jsonb not null default '{}'::jsonb;  -- {"charger": 20, "handsfree": 15}
alter table vendors add column if not exists variant_prices jsonb not null default '{}'::jsonb;  -- {"gray": 690}
alter table vendors add column if not exists addons jsonb not null default '[]'::jsonb;  -- [{"key": "charger", "min_price": null}]

-- the assistant chat: one conversation that never closes. You can always write, and a new purchase request starts a new deal.
create table if not exists assistant_threads (
  id text primary key,                          -- 'main' (there is one thread, the app has no accounts)
  state jsonb not null default '{}'::jsonb,     -- the purchase being prepared, and what the assistant waits for
  updated_at timestamptz not null default now()
);
create table if not exists assistant_messages (
  id uuid primary key default gen_random_uuid(),
  thread_id text not null default 'main',
  sender text not null check (sender in ('user', 'assistant')),
  text text not null,
  deal_id uuid,                                 -- the deal this message started or is about
  created_at timestamptz not null default now()
);
create index if not exists assistant_messages_thread_idx on assistant_messages (thread_id, created_at);
alter table assistant_threads enable row level security;
alter table assistant_messages enable row level security;
