-- Restart-safe import support for explicit legacy review-history IDs.
create or replace function public.sync_review_history_identity()
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  max_id bigint;
  sequence_name text := pg_get_serial_sequence('public.review_history', 'id');
begin
  select max(id) into max_id from public.review_history;
  if max_id is null then
    perform setval(sequence_name, 1, false);
  else
    perform setval(sequence_name, max_id, true);
  end if;
end;
$$;

revoke all on function public.sync_review_history_identity() from public, anon, authenticated;
grant execute on function public.sync_review_history_identity() to service_role;
