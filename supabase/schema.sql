-- ============================================================
--  HSK Flashcards — database schema, RLS, and sync RPCs.
--  Run this once in Supabase → SQL Editor (or via CLI migration).
--  Safe to re-run (idempotent).
-- ============================================================

-- ---------- Tables ----------
create table if not exists public.profiles (
  id         uuid primary key references auth.users(id) on delete cascade,
  username   text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- Case-insensitive uniqueness for usernames.
create unique index if not exists profiles_username_lower_idx on public.profiles (lower(username));

create table if not exists public.card_progress (
  user_id    uuid not null references auth.users(id) on delete cascade,
  card_id    int  not null,
  due        date,
  interval   int  not null default 0,
  reps       int  not null default 0,
  correct    int  not null default 0,
  attempts   int  not null default 0,
  updated_at timestamptz not null default now(),
  primary key (user_id, card_id)
);
create index if not exists card_progress_user_updated_idx on public.card_progress (user_id, updated_at);

create table if not exists public.user_settings (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  data       jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

-- Rate-limiting store (server-only; NEVER exposed to clients).
create table if not exists public.login_attempts (
  username     text primary key,
  fails        int not null default 0,
  locked_until timestamptz
);

-- ---------- Row Level Security ----------
alter table public.profiles       enable row level security;
alter table public.card_progress  enable row level security;
alter table public.user_settings  enable row level security;
alter table public.login_attempts enable row level security;  -- enabled + NO policies => no client access

drop policy if exists "own profile read"   on public.profiles;
drop policy if exists "own profile insert" on public.profiles;
drop policy if exists "own profile update" on public.profiles;
create policy "own profile read"   on public.profiles for select using (auth.uid() = id);
create policy "own profile insert" on public.profiles for insert with check (auth.uid() = id);
create policy "own profile update" on public.profiles for update using (auth.uid() = id) with check (auth.uid() = id);

drop policy if exists "own progress" on public.card_progress;
create policy "own progress" on public.card_progress for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "own settings" on public.user_settings;
create policy "own settings" on public.user_settings for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ---------- Grants ----------
grant select, insert, update, delete on public.profiles, public.card_progress, public.user_settings to authenticated;
revoke all on public.login_attempts from anon, authenticated;  -- service role only

-- ---------- Sync RPCs (latest updated_at wins; never overwrite newer) ----------
create or replace function public.sync_push_progress(rows jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare uid uuid := auth.uid();
begin
  if uid is null then raise exception 'not authenticated'; end if;
  insert into public.card_progress (user_id, card_id, due, interval, reps, correct, attempts, updated_at)
  select uid,
         (r->>'card_id')::int,
         nullif(r->>'due','')::date,
         coalesce((r->>'interval')::int, 0),
         coalesce((r->>'reps')::int, 0),
         coalesce((r->>'correct')::int, 0),
         coalesce((r->>'attempts')::int, 0),
         coalesce((r->>'updated_at')::timestamptz, now())
  from jsonb_array_elements(rows) as r
  on conflict (user_id, card_id) do update
    set due=excluded.due, interval=excluded.interval, reps=excluded.reps,
        correct=excluded.correct, attempts=excluded.attempts, updated_at=excluded.updated_at
    where excluded.updated_at > public.card_progress.updated_at;   -- newer-only
end;
$$;

create or replace function public.sync_push_settings(p_data jsonb, p_updated_at timestamptz)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare uid uuid := auth.uid();
begin
  if uid is null then raise exception 'not authenticated'; end if;
  insert into public.user_settings (user_id, data, updated_at)
  values (uid, coalesce(p_data,'{}'::jsonb), coalesce(p_updated_at, now()))
  on conflict (user_id) do update
    set data=excluded.data, updated_at=excluded.updated_at
    where excluded.updated_at > public.user_settings.updated_at;    -- newer-only
end;
$$;

grant execute on function public.sync_push_progress(jsonb) to authenticated;
grant execute on function public.sync_push_settings(jsonb, timestamptz) to authenticated;
