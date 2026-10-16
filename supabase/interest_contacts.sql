-- Launch-update signups from the form at the bottom of the process details panel.
-- Run this once in the Supabase SQL editor. It is safe to run again.
--
-- The site calls Supabase with the project's publishable (anon) key, which is public by design.
-- With these settings that key can only call subscribe_interest(): it cannot read, change or
-- delete any row. Read the list in the Table Editor or the SQL editor, which sign in as the owner.

-- One row per email and process: the box the person had open when they signed up.
create table if not exists public.supply_chain_ai_index_interest_contacts (
  id bigint generated always as identity primary key,
  email text not null,
  process_id text not null,
  process_name text,
  process_group text,
  country text,
  role text,
  created_at timestamptz not null default now(),
  constraint email_format check (char_length(email) <= 254 and email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  constraint process_id_length check (char_length(process_id) between 1 and 64),
  constraint process_name_length check (char_length(process_name) <= 200),
  constraint process_group_length check (char_length(process_group) <= 100),
  constraint country_code check (country in ('NA', 'US', 'CA')),
  constraint role_length check (char_length(role) <= 200),
  constraint one_signup_per_process unique (email, process_id)
);

-- RLS on with no policies: the public key gets no direct access to the table.
alter table public.supply_chain_ai_index_interest_contacts enable row level security;
revoke all on table public.supply_chain_ai_index_interest_contacts from anon, authenticated;

-- Rate limiting. Hashed client IPs, kept for one day, in a schema the API does not expose.
create schema if not exists private;
revoke all on schema private from anon, authenticated;
create table if not exists private.sc_ai_index_signup_log (
  ip_hash text,
  created_at timestamptz not null default now()
);
create index if not exists sc_ai_index_signup_log_created_at on private.sc_ai_index_signup_log (created_at);
revoke all on table private.sc_ai_index_signup_log from anon, authenticated;

-- The only thing the public key can do: add one signup. Returns nothing, so it never reveals
-- whether an email is already on the list. Limits: 10 per IP and 6000 overall per hour.
create or replace function public.subscribe_interest(
  p_email text,
  p_process_id text,
  p_process_name text default null,
  p_process_group text default null,
  p_country text default null,
  p_role text default null
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  -- Cloudflare sets this header in front of Supabase; callers cannot override it.
  client_ip text := nullif(current_setting('request.headers', true)::json->>'cf-connecting-ip', '');
  ip_key text := case when client_ip is null then null else encode(sha256(convert_to(client_ip, 'UTF8')), 'hex') end;
begin
  delete from private.sc_ai_index_signup_log where created_at < now() - interval '1 day';

  if (select count(*) from private.sc_ai_index_signup_log where created_at > now() - interval '1 hour') >= 6000
     or (ip_key is not null and (select count(*) from private.sc_ai_index_signup_log
                                 where ip_hash = ip_key and created_at > now() - interval '1 hour') >= 10) then
    raise sqlstate 'PGRST' using
      message = json_build_object('code', 'rate_limited', 'message', 'Too many signups. Try again later.')::text,
      detail = json_build_object('status', 429, 'headers', json_build_object('Retry-After', '3600'))::text;
  end if;

  insert into private.sc_ai_index_signup_log (ip_hash) values (ip_key);

  -- A failed check would echo the whole row back, including the id (which shows how many
  -- signups there are), so callers get a plain 400 instead.
  begin
    insert into public.supply_chain_ai_index_interest_contacts (email, process_id, process_name, process_group, country, role)
    values (lower(trim(p_email)), p_process_id, p_process_name, p_process_group, p_country, nullif(trim(p_role), ''))
    on conflict (email, process_id) do nothing;
  exception when check_violation or not_null_violation then
    raise sqlstate 'PGRST' using
      message = json_build_object('code', 'invalid_signup', 'message', 'Invalid signup.')::text,
      detail = json_build_object('status', 400, 'headers', json_build_object())::text;
  end;
end;
$$;

revoke all on function public.subscribe_interest(text, text, text, text, text, text) from public, anon, authenticated;
grant execute on function public.subscribe_interest(text, text, text, text, text, text) to anon, authenticated;
