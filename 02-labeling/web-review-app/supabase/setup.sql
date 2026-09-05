-- Run this once in Supabase: SQL Editor -> New query -> Run.
-- The app uses anonymous Supabase Auth users; no email login is required.

create extension if not exists pgcrypto;

create table if not exists public.labeling_candidates (
  queue_order bigint generated always as identity primary key,
  candidate_id text not null unique,
  source text not null,
  source_record_id text not null,
  narrative text not null,
  source_native_outcome text not null default '',
  activity_if_known text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists public.labeling_decisions (
  decision_id uuid primary key default gen_random_uuid(),
  candidate_id text not null references public.labeling_candidates(candidate_id),
  reviewer_id uuid not null default auth.uid() references auth.users(id),
  reviewer_name text not null check (char_length(trim(reviewer_name)) between 2 and 100),
  sif_label text not null check (sif_label in ('SIF_POTENTIAL', 'NON_SIF_POTENTIAL', 'UNCERTAIN', 'SKIP')),
  confidence numeric(3,2) not null check (confidence between 0 and 1),
  hazard text not null default '',
  exposure text not null default '',
  barrier_failure text not null default '',
  credible_consequence text not null default '',
  reason text not null default '',
  client_timezone text not null default '',
  source_snapshot text not null default '',
  source_record_id_snapshot text not null default '',
  narrative_snapshot text not null default '',
  native_outcome_snapshot text not null default '',
  activity_snapshot text not null default '',
  submitted_at timestamptz not null default now(),
  unique (candidate_id, reviewer_id)
);

create or replace function public.copy_candidate_snapshot()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  select source, source_record_id, narrative, source_native_outcome, activity_if_known
    into new.source_snapshot, new.source_record_id_snapshot, new.narrative_snapshot,
         new.native_outcome_snapshot, new.activity_snapshot
  from public.labeling_candidates
  where candidate_id = new.candidate_id;

  if not found then
    raise exception 'Unknown candidate_id';
  end if;
  return new;
end;
$$;

drop trigger if exists copy_candidate_snapshot_before_insert on public.labeling_decisions;
create trigger copy_candidate_snapshot_before_insert
before insert on public.labeling_decisions
for each row execute function public.copy_candidate_snapshot();

alter table public.labeling_candidates enable row level security;
alter table public.labeling_decisions enable row level security;

revoke all on public.labeling_candidates from anon, authenticated;
revoke all on public.labeling_decisions from anon, authenticated;
grant select on public.labeling_candidates to authenticated;
grant select, insert on public.labeling_decisions to authenticated;

drop policy if exists "authenticated reviewers can read candidates" on public.labeling_candidates;
create policy "authenticated reviewers can read candidates"
on public.labeling_candidates for select
to authenticated
using (true);

drop policy if exists "reviewers can read own decisions" on public.labeling_decisions;
drop policy if exists "authenticated reviewers can read all decisions" on public.labeling_decisions;
create policy "authenticated reviewers can read all decisions"
on public.labeling_decisions for select
to authenticated
using (true);

drop policy if exists "reviewers can insert own decisions" on public.labeling_decisions;
create policy "reviewers can insert own decisions"
on public.labeling_decisions for insert
to authenticated
with check ((select auth.uid()) = reviewer_id);

revoke all on function public.copy_candidate_snapshot() from public;

create index if not exists labeling_decisions_reviewer_idx
on public.labeling_decisions(reviewer_id, submitted_at);

create index if not exists labeling_decisions_candidate_idx
on public.labeling_decisions(candidate_id, submitted_at);

-- Make new decisions appear live in every connected labeling app.
do $$
begin
  if not exists (
    select 1
    from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'labeling_decisions'
  ) then
    alter publication supabase_realtime add table public.labeling_decisions;
  end if;
end
$$;
