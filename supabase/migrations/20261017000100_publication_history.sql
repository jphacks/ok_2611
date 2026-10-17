-- P1：menus.account_id（本人の読み込み履歴・所有者）、履歴索引、ゲストの同意false制約、
-- save_menu_analysis の所有者引数追加と登録時同意のコピー。
-- 正本は docs/database.md の menus・save_menu_analysis・読み取り範囲。
-- 既存のP0データは所有者NULL・同意falseのまま残る（ゲストの解析を後から移管しない）。

-- ---------------------------------------------------------------------------
-- 所有者列・制約・索引
-- ---------------------------------------------------------------------------

alter table public.menus
  add column account_id uuid references public.accounts (id) on delete restrict;

alter table public.menus
  add constraint menus_guest_consent_check
  check (account_id is not null or user_publish_consent = false);

create index idx_menus_account_created
  on public.menus (account_id, created_at desc, id desc);

-- ---------------------------------------------------------------------------
-- RPC: save_menu_analysis（P1版）
-- ---------------------------------------------------------------------------

-- 引数違いの旧関数を残さない。
drop function public.save_menu_analysis(uuid, text, text, jsonb, text, text, timestamptz);

-- メニュー1件と料理1〜20件を1トランザクションで登録し、menu_id を返す。
-- p_account_id はAPIが検証済みアカウントJWTの sub から渡す（ゲストはNULL）。
-- 利用者同意は引数で受け取らず、accounts.publish_consent をコピーする。ゲストはfalse。
create function public.save_menu_analysis(
  p_restaurant_id uuid,
  p_image_path text,
  p_analysis_token_hash text,
  p_dishes jsonb,
  p_ai_model text,
  p_prompt_version text,
  p_analysis_expires_at timestamptz default null,
  p_account_id uuid default null
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_menu_id uuid;
  v_dish jsonb;
  v_count integer;
  v_user_publish_consent boolean := false;
begin
  if p_account_id is not null then
    select a.publish_consent
      into v_user_publish_consent
      from public.accounts a
     where a.id = p_account_id;
    if not found then
      raise exception 'account_not_found' using errcode = 'P0002';
    end if;
  end if;

  if p_analysis_token_hash is null or p_analysis_token_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid_analysis_token_hash' using errcode = '22023';
  end if;

  if p_dishes is null or jsonb_typeof(p_dishes) <> 'array' then
    raise exception 'dishes_invalid' using errcode = '22023';
  end if;

  v_count := jsonb_array_length(p_dishes);
  if v_count < 1 or v_count > 20 then
    raise exception 'dishes_invalid' using errcode = '22023';
  end if;

  for v_dish in select e.value from jsonb_array_elements(p_dishes) as e(value) loop
    if jsonb_typeof(v_dish) <> 'object' then
      raise exception 'dishes_invalid' using errcode = '22023';
    end if;
    if exists (
         select 1
           from jsonb_object_keys(v_dish) as k(key)
          where k.key not in ('name', 'name_key', 'translations', 'price', 'currency', 'ai_result')
       )
       or jsonb_typeof(v_dish -> 'name') is distinct from 'string'
       or jsonb_typeof(v_dish -> 'name_key') is distinct from 'string'
       or jsonb_typeof(v_dish -> 'translations') is distinct from 'object'
       or jsonb_typeof(v_dish -> 'ai_result') is distinct from 'object'
       or coalesce(jsonb_typeof(v_dish -> 'price'), 'null') not in ('number', 'null')
       or coalesce(jsonb_typeof(v_dish -> 'currency'), 'null') not in ('string', 'null')
    then
      raise exception 'dishes_invalid' using errcode = '22023';
    end if;
  end loop;

  insert into public.menus (
    restaurant_id,
    account_id,
    user_publish_consent,
    image_path,
    analysis_token_hash,
    analysis_expires_at
  )
  values (
    p_restaurant_id,
    p_account_id,
    v_user_publish_consent,
    p_image_path,
    p_analysis_token_hash,
    coalesce(p_analysis_expires_at, now() + interval '24 hours')
  )
  returning id into v_menu_id;

  insert into public.dishes (
    menu_id,
    name,
    position,
    name_key,
    translations,
    price,
    currency,
    ai_result,
    ai_model,
    prompt_version
  )
  select
    v_menu_id,
    e.value ->> 'name',
    e.ordinality::smallint,
    e.value ->> 'name_key',
    e.value -> 'translations',
    (e.value ->> 'price')::numeric(10, 2),
    coalesce(e.value ->> 'currency', 'JPY'),
    e.value -> 'ai_result',
    p_ai_model,
    p_prompt_version
  from jsonb_array_elements(p_dishes) with ordinality as e(value, ordinality);

  return v_menu_id;
end;
$$;

revoke all on function
  public.save_menu_analysis(uuid, text, text, jsonb, text, text, timestamptz, uuid)
from public, anon, authenticated, service_role;

grant execute on function
  public.save_menu_analysis(uuid, text, text, jsonb, text, text, timestamptz, uuid)
to service_role;
