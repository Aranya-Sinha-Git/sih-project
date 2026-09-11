-- Production account roles. New self-service accounts are least-privileged
-- members; reviewer and admin remain explicit server-managed roles.
update public.profiles
set role = 'member'
where role = 'demo';

alter table public.profiles
  drop constraint if exists profiles_role_check;

alter table public.profiles
  add constraint profiles_role_check
  check (role in ('member', 'reviewer', 'admin'));

alter table public.profiles
  alter column role set default 'member';

create unique index if not exists profiles_username_case_insensitive_idx
  on public.profiles (lower(username));
