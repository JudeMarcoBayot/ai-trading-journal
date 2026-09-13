create table if not exists public.trade_logs (
  id uuid primary key default gen_random_uuid(),
  symbol text not null,
  direction text not null check (direction in ('long', 'short')),
  entry_price numeric(18, 6) not null check (entry_price > 0),
  exit_price numeric(18, 6) check (exit_price is null or exit_price > 0),
  position_size numeric(18, 6) not null check (position_size > 0),
  notes text not null default '',
  created_at timestamptz not null default now()
);

create index if not exists trade_logs_created_at_idx on public.trade_logs (created_at desc);

create table if not exists public.bybit_executions (
  id uuid primary key default gen_random_uuid(),
  external_id text not null unique,
  order_id text,
  symbol text not null,
  category text not null default 'linear',
  side text not null check (side in ('Buy', 'Sell')),
  quantity numeric(28, 10) not null,
  price numeric(28, 10) not null,
  realized_pnl numeric(28, 10) not null default 0,
  fee numeric(28, 10) not null default 0,
  fee_currency text,
  executed_at timestamptz not null,
  is_maker boolean not null default false,
  stop_loss numeric(28, 10),
  take_profit numeric(28, 10),
  stop_order_type text,
  create_type text,
  entry_price numeric(28, 10),
  created_at timestamptz not null default now()
);

create index if not exists bybit_executions_executed_at_idx
  on public.bybit_executions (executed_at desc);

create index if not exists bybit_executions_symbol_idx
  on public.bybit_executions (symbol);

alter table if exists public.bybit_executions
  add column if not exists stop_loss numeric(28, 10);

alter table if exists public.bybit_executions
  add column if not exists take_profit numeric(28, 10);

alter table if exists public.bybit_executions
  add column if not exists stop_order_type text;

alter table if exists public.bybit_executions
  add column if not exists create_type text;

alter table if exists public.bybit_executions
  add column if not exists entry_price numeric(28, 10);

create table if not exists public.ai_analyses (
  id uuid primary key default gen_random_uuid(),
  provider text not null,
  summary text not null,
  trade_reviews jsonb not null default '[]'::jsonb,
  chart_review text not null default '',
  technical_review text not null default '',
  fee_impact text not null,
  long_vs_short text not null,
  repeated_patterns jsonb not null default '[]'::jsonb,
  risk_suggestions jsonb not null default '[]'::jsonb,
  discipline_suggestions jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

alter table if exists public.ai_analyses
  add column if not exists trade_reviews jsonb default '[]'::jsonb;

alter table if exists public.ai_analyses
  add column if not exists chart_review text default '';

alter table if exists public.ai_analyses
  add column if not exists technical_review text default '';

alter table if exists public.ai_analyses
  drop column if exists best_symbol;

alter table if exists public.ai_analyses
  drop column if exists worst_symbol;

create index if not exists ai_analyses_created_at_idx
  on public.ai_analyses (created_at desc);

create table if not exists public.trading_knowledge (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  content text not null,
  tags jsonb not null default '[]'::jsonb,
  category text not null default 'trading_rule',
  created_at timestamptz not null default now()
);

create index if not exists trading_knowledge_created_at_idx
  on public.trading_knowledge (created_at desc);

create index if not exists trading_knowledge_category_idx
  on public.trading_knowledge (category);

