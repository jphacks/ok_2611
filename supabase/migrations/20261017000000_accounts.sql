-- P1：アカウント3テーブル、本人設定の置換RPC2つ、RLS・権限。
-- 正本は docs/database.md の accounts・account_allergens・account_dietary_restrictions と各RPC。
-- Supabase Auth（auth.users）やログインセッション用のテーブルは使わない。

-- ---------------------------------------------------------------------------
-- テーブル
-- ---------------------------------------------------------------------------

create table public.accounts (
  id uuid primary key default gen_random_uuid(),
  email text not null
    constraint accounts_email_lower check (email = lower(email))
    constraint accounts_email_trimmed check (email !~ '^\s' and email !~ '\s$')
    constraint accounts_email_length check (char_length(email) between 3 and 254),
  nickname text not null
    constraint accounts_nickname_trimmed check (nickname !~ '^\s' and nickname !~ '\s$')
    constraint accounts_nickname_length check (char_length(nickname) between 1 and 30),
  password_hash text not null
    constraint accounts_password_hash_argon2id check (starts_with(password_hash, '$argon2id$')),
  publish_consent boolean not null,
  publish_consent_recorded_at timestamptz not null default now(),
  publish_consent_version text not null
    constraint accounts_publish_consent_version_nonempty check (char_length(publish_consent_version) >= 1),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint accounts_email_key unique (email)
);

create table public.account_allergens (
  account_id uuid not null references public.accounts (id) on delete cascade,
  allergen_id smallint not null references public.allergens (id) on delete restrict,
  created_at timestamptz not null default now(),
  primary key (account_id, allergen_id)
);

create table public.account_dietary_restrictions (
  account_id uuid not null references public.accounts (id) on delete cascade,
  dietary_restriction_id smallint not null references public.dietary_restrictions (id) on delete restrict,
  created_at timestamptz not null default now(),
  primary key (account_id, dietary_restriction_id)
);

-- ---------------------------------------------------------------------------
-- RPC: 本人設定の全件置換
-- ---------------------------------------------------------------------------

-- 本人のアレルゲンを1トランザクションで全件置き換え、置き換え後のIDを昇順で返す。
-- p_account_id はAPIがアカウント用トークンの sub から渡す。空配列は全解除。
create function public.replace_account_allergens(
  p_account_id uuid,
  p_allergen_ids jsonb
)
returns smallint[]
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_item jsonb;
  v_ids smallint[] := '{}'::smallint[];
begin
  -- 同じ本人の同時保存を直列化する
  perform 1 from public.accounts a where a.id = p_account_id for update;
  if not found then
    raise exception 'account_not_found' using errcode = 'P0002';
  end if;

  if p_allergen_ids is null or jsonb_typeof(p_allergen_ids) <> 'array' then
    raise exception 'invalid_allergen_ids' using errcode = '22023';
  end if;

  for v_item in select e.value from jsonb_array_elements(p_allergen_ids) as e(value) loop
    if jsonb_typeof(v_item) <> 'number' or (v_item #>> '{}') !~ '^[0-9]{1,4}$' then
      raise exception 'invalid_allergen_ids' using errcode = '22023';
    end if;
    v_ids := v_ids || (v_item #>> '{}')::smallint;
  end loop;

  if cardinality(v_ids) <> (select count(distinct x) from unnest(v_ids) as x)
     or exists (select 1 from unnest(v_ids) as x
                 where not exists (select 1 from public.allergens m where m.id = x)) then
    raise exception 'invalid_allergen_ids' using errcode = '22023';
  end if;

  delete from public.account_allergens aa where aa.account_id = p_account_id;

  insert into public.account_allergens (account_id, allergen_id)
  select p_account_id, x from unnest(v_ids) as x;

  return coalesce(
    (select array_agg(aa.allergen_id order by aa.allergen_id)
       from public.account_allergens aa
      where aa.account_id = p_account_id),
    '{}'::smallint[]);
end;
$$;

-- 本人の食事制限を1トランザクションで全件置き換え、置き換え後のIDを昇順で返す。
create function public.replace_account_dietary_restrictions(
  p_account_id uuid,
  p_dietary_restriction_ids jsonb
)
returns smallint[]
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_item jsonb;
  v_ids smallint[] := '{}'::smallint[];
begin
  perform 1 from public.accounts a where a.id = p_account_id for update;
  if not found then
    raise exception 'account_not_found' using errcode = 'P0002';
  end if;

  if p_dietary_restriction_ids is null or jsonb_typeof(p_dietary_restriction_ids) <> 'array' then
    raise exception 'invalid_dietary_restriction_ids' using errcode = '22023';
  end if;

  for v_item in select e.value from jsonb_array_elements(p_dietary_restriction_ids) as e(value) loop
    if jsonb_typeof(v_item) <> 'number' or (v_item #>> '{}') !~ '^[0-9]{1,4}$' then
      raise exception 'invalid_dietary_restriction_ids' using errcode = '22023';
    end if;
    v_ids := v_ids || (v_item #>> '{}')::smallint;
  end loop;

  if cardinality(v_ids) <> (select count(distinct x) from unnest(v_ids) as x)
     or exists (select 1 from unnest(v_ids) as x
                 where not exists (select 1 from public.dietary_restrictions m where m.id = x)) then
    raise exception 'invalid_dietary_restriction_ids' using errcode = '22023';
  end if;

  delete from public.account_dietary_restrictions ad where ad.account_id = p_account_id;

  insert into public.account_dietary_restrictions (account_id, dietary_restriction_id)
  select p_account_id, x from unnest(v_ids) as x;

  return coalesce(
    (select array_agg(ad.dietary_restriction_id order by ad.dietary_restriction_id)
       from public.account_dietary_restrictions ad
      where ad.account_id = p_account_id),
    '{}'::smallint[]);
end;
$$;

-- ---------------------------------------------------------------------------
-- RLS・権限
-- ---------------------------------------------------------------------------

alter table public.accounts enable row level security;
alter table public.account_allergens enable row level security;
alter table public.account_dietary_restrictions enable row level security;

revoke all on table
  public.accounts,
  public.account_allergens,
  public.account_dietary_restrictions
from public, anon, authenticated, service_role;

-- accounts の追加は登録時の入力列だけに限定する。
-- id・publish_consent_recorded_at・created_at・updated_at はDBの既定値（gen_random_uuid()・now()）で決め、APIから指定させない。
grant select on table public.accounts to service_role;
grant insert (email, nickname, password_hash, publish_consent, publish_consent_version)
  on table public.accounts to service_role;
-- パスワードの再ハッシュと、置換RPCの FOR UPDATE に必要な列だけ。同意・本人情報は更新させない。
grant update (password_hash, updated_at) on table public.accounts to service_role;

grant select, insert, delete on table
  public.account_allergens,
  public.account_dietary_restrictions
to service_role;

revoke all on function
  public.replace_account_allergens(uuid, jsonb),
  public.replace_account_dietary_restrictions(uuid, jsonb)
from public, anon, authenticated, service_role;

grant execute on function
  public.replace_account_allergens(uuid, jsonb),
  public.replace_account_dietary_restrictions(uuid, jsonb)
to service_role;
