-- DealDesk database functions. Paste this into the Supabase SQL editor and run it.
-- Safe to run more than once.
--
-- consume_llm_call: counts one model call against BOTH the daily budget and the per-deal budget,
-- in a single transaction. The row locks make it exact even when many calls arrive at the same moment.
-- It returns 'ok', 'daily_exhausted', 'deal_exhausted' or 'unknown_deal'. Nothing is counted unless it returns 'ok'.

create or replace function consume_llm_call(p_day date, p_deal_id uuid, p_daily_cap int, p_deal_cap int)
returns text
language plpgsql
security invoker
set search_path = public
as $$
declare
  deal_count int;
  daily_count int;
begin
  if p_deal_id is not null then
    select llm_calls into deal_count from deals where id = p_deal_id for update;
    if not found then
      return 'unknown_deal';
    end if;
    if deal_count >= p_deal_cap then
      return 'deal_exhausted';
    end if;
  end if;

  insert into usage_counters (day, kind, count) values (p_day, 'llm', 0)
    on conflict (day, kind) do nothing;
  select count into daily_count from usage_counters where day = p_day and kind = 'llm' for update;
  if daily_count >= p_daily_cap then
    return 'daily_exhausted';
  end if;

  update usage_counters set count = count + 1 where day = p_day and kind = 'llm';
  if p_deal_id is not null then
    update deals set llm_calls = llm_calls + 1 where id = p_deal_id;
  end if;
  return 'ok';
end;
$$;

-- Only the server (service role) may call it. The public anon key must not be able to burn the budget.
revoke all on function consume_llm_call(date, uuid, int, int) from public, anon, authenticated;
grant execute on function consume_llm_call(date, uuid, int, int) to service_role;
