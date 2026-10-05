-- Search credit counter. Paste into the Supabase SQL editor and run it. Safe to run more than once.
--
-- consume_search_credits: adds `p_amount` Tavily credits to today's row, but only if the whole month stays
-- within `p_monthly_cap`. Returns 'ok' or 'monthly_exhausted'. Nothing is counted unless it returns 'ok'.
-- An advisory lock makes two searches at the same moment count exactly.

create or replace function consume_search_credits(p_day date, p_amount int, p_monthly_cap int)
returns text
language plpgsql
security invoker
set search_path = public
as $$
declare
  used int;
begin
  perform pg_advisory_xact_lock(hashtext('consume_search_credits'));

  select coalesce(sum(count), 0) into used
  from usage_counters
  where kind = 'tavily'
    and day >= date_trunc('month', p_day)::date
    and day < (date_trunc('month', p_day) + interval '1 month')::date;

  if used + p_amount > p_monthly_cap then
    return 'monthly_exhausted';
  end if;

  insert into usage_counters (day, kind, count) values (p_day, 'tavily', p_amount)
    on conflict (day, kind) do update set count = usage_counters.count + p_amount;
  return 'ok';
end;
$$;

revoke all on function consume_search_credits(date, int, int) from public, anon, authenticated;
grant execute on function consume_search_credits(date, int, int) to service_role;
