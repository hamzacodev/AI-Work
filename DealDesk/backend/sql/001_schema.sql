-- DealDesk schema. Paste this into the Supabase SQL editor and run it.
-- Safe to run more than once.
-- Security: Row Level Security is ON for every table with NO policies, so only
-- the backend (service role key) can read or write. Never expose that key.

create table if not exists deals (
  id uuid primary key default gen_random_uuid(),
  item text not null,
  max_price numeric not null check (max_price > 0),
  currency text not null,
  must_haves text[] not null default '{}',
  address text,
  phone text,
  status text not null default 'created',
  research jsonb,
  llm_calls int not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists vendors (
  id uuid primary key default gen_random_uuid(),
  deal_id uuid not null references deals(id) on delete cascade,
  name text not null,
  contact text not null,
  channel text not null default 'email' check (channel in ('email', 'chat')),
  status text not null default 'sent'
    check (status in ('sent', 'replied', 'negotiating', 'needs_you', 'closed', 'blocked')),
  offer_price numeric,
  last_counter numeric,
  rounds int not null default 0,
  stall_count int not null default 0,
  recommendation jsonb,
  persona text,                       -- simulator only
  lease_until timestamptz,            -- a task holds this while working on the vendor
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create table if not exists messages (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references vendors(id) on delete cascade,
  sender text not null check (sender in ('vendor', 'agent', 'owner')),
  text text not null,
  simulated boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists events (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references vendors(id) on delete cascade,
  agent text not null,
  text text not null,
  sources jsonb,
  created_at timestamptz not null default now()
);

create table if not exists research_cache (
  key text primary key,
  result jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists eval_runs (
  id uuid primary key default gen_random_uuid(),
  model text not null,
  judge_model text,
  judge_note text,
  mode text not null check (mode in ('safety_off', 'safety_on')),
  n_deals int not null,
  metrics jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists usage_counters (
  day date not null,
  kind text not null,                 -- 'llm' or 'tavily'
  count int not null default 0,
  primary key (day, kind)
);

create index if not exists vendors_deal_id_idx on vendors (deal_id);
create index if not exists vendors_resume_idx on vendors (status, lease_until);
create index if not exists messages_vendor_id_idx on messages (vendor_id, created_at);
create index if not exists events_vendor_id_idx on events (vendor_id, created_at);

alter table deals enable row level security;
alter table vendors enable row level security;
alter table messages enable row level security;
alter table events enable row level security;
alter table research_cache enable row level security;
alter table eval_runs enable row level security;
alter table usage_counters enable row level security;
