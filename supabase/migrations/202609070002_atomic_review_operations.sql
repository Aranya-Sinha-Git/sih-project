-- Atomic server-side review operation. FastAPI authorizes the caller before
-- invoking this function; the browser has no execute grant.
create or replace function public.apply_incident_review(
  p_incident_id text,
  p_status text,
  p_reviewer text,
  p_reviewer_user_id uuid,
  p_comment text,
  p_sif_potential boolean,
  p_label_status text,
  p_outcome text,
  p_timestamp timestamptz,
  p_previous_outcome text,
  p_screening_version text
) returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.incidents
     set review_status = p_status,
         reviewer = p_reviewer,
         review_comment = p_comment,
         sif_potential = p_sif_potential,
         sif_label_status = p_label_status
   where id = p_incident_id;

  if not found then
    raise exception 'Incident not found: %', p_incident_id using errcode = 'P0002';
  end if;

  insert into public.review_history (
    incident_id, outcome, reviewer, reviewer_user_id, comment, timestamp,
    previous_outcome, new_outcome, screening_version
  ) values (
    p_incident_id, p_outcome, p_reviewer, p_reviewer_user_id, p_comment,
    coalesce(p_timestamp, now()), p_previous_outcome, p_outcome,
    p_screening_version
  );
end;
$$;

revoke all on function public.apply_incident_review(text, text, text, uuid, text, boolean, text, text, timestamptz, text, text) from public, anon, authenticated;
grant execute on function public.apply_incident_review(text, text, text, uuid, text, boolean, text, text, timestamptz, text, text) to service_role;
