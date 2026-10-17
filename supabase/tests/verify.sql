-- P0のDB検証（01）。マイグレーションではない。
-- 1つのトランザクション内で実行し、最後に必ずROLLBACKする（成功時も検証データを残さない）。
-- 期待と異なる結果・想定外の例外は ON_ERROR_STOP で即時に終了コード3となる。
-- 実行方法・結果は supabase/README.md を参照。
-- 失敗検出の確認： -v inject_failure=1 を付けると最後に意図的に失敗する。
--
-- 対象外（03で実施）：複数接続による並行実行、Supabase SDK経由のRPC、実Storageのアップロード・削除。
-- 対象外（02で実施）：アカウント・所有者・利用者同意trueを含む公開条件の8通り。

\set ON_ERROR_STOP on
\pset pager off
\set QUIET on

begin;

-- ---------------------------------------------------------------------------
-- 検証用ヘルパー（pg_temp。ロールバックで消える）
-- ---------------------------------------------------------------------------

create function pg_temp.assert(p_cond boolean, p_msg text)
returns void
language plpgsql
as $$
begin
  if p_cond is distinct from true then
    raise exception 'FAIL: %', p_msg;
  end if;
end;
$$;

-- 指定ロールで p_sql を実行し、単一の jsonb を返す。終了時に元のロールへ戻す。
create function pg_temp.exec_as(p_role text, p_sql text)
returns jsonb
language plpgsql
as $$
declare
  v_result jsonb;
begin
  execute format('set local role %I', p_role);
  execute p_sql into v_result;
  execute 'reset role';
  return v_result;
end;
$$;

-- 指定ロールで p_sql を実行し、SQLSTATE（とメッセージ）が一致する例外になることを確認する。
-- 実行はサブトランザクション内で行い、成功・失敗にかかわらずその変更とロールを巻き戻す。
create function pg_temp.expect_error(p_role text, p_sql text, p_state text, p_msg text default null)
returns void
language plpgsql
as $$
declare
  v_succeeded boolean := false;
  v_state text;
  v_msg text;
begin
  begin
    execute format('set local role %I', p_role);
    execute p_sql;
    v_succeeded := true;
    raise exception 'rollback_probe' using errcode = 'P0999';
  exception when others then
    get stacked diagnostics v_state = returned_sqlstate, v_msg = message_text;
  end;

  if v_succeeded then
    raise exception 'FAIL: expected % % but succeeded (role %): %', p_state, coalesce(p_msg, ''), p_role, p_sql;
  end if;
  if v_state <> p_state or (p_msg is not null and v_msg <> p_msg) then
    raise exception 'FAIL: expected % % but got % % (role %): %',
      p_state, coalesce(p_msg, ''), v_state, v_msg, p_role, p_sql;
  end if;
end;
$$;

create function pg_temp.put(p_key text, p_value text)
returns void
language sql
as $$ select set_config('verify.' || p_key, p_value, true); $$;

create function pg_temp.get(p_key text)
returns text
language sql
as $$ select current_setting('verify.' || p_key); $$;

create function pg_temp.h(p_token text)
returns text
language sql
as $$ select encode(sha256(convert_to(p_token, 'UTF8')), 'hex'); $$;

create function pg_temp.dish(p_name text, p_price numeric default null, p_with_currency boolean default true)
returns jsonb
language sql
as $$
  select jsonb_build_object(
    'name', p_name,
    'name_key', lower(replace(p_name, ' ', '')),
    'translations', jsonb_build_object('en', jsonb_build_object('name', p_name, 'description', 'AI description')),
    'price', p_price,
    'ai_result', '{"ingredients":[],"allergens":[],"dietary_restrictions":[]}'::jsonb
  ) || case when p_with_currency then '{"currency":"JPY"}'::jsonb else '{}'::jsonb end;
$$;

create function pg_temp.dishes(p_count integer)
returns jsonb
language sql
as $$
  select coalesce(jsonb_agg(pg_temp.dish('Dish ' || i, 100 * i) order by i), '[]'::jsonb)
    from generate_series(1, p_count) as i;
$$;

create function pg_temp.save_sql(
  p_restaurant_id uuid, p_image_path text, p_hash text, p_dishes jsonb, p_expires_at timestamptz default null
)
returns text
language sql
as $$
  select format(
    'select to_jsonb(public.save_menu_analysis(%L::uuid, %L, %L, %L::jsonb, %L, %L, %L::timestamptz))',
    p_restaurant_id, p_image_path, p_hash, p_dishes, 'gemini-test', 'v4', p_expires_at
  );
$$;

create function pg_temp.confirm_sql(
  p_menu_id uuid, p_hash text, p_request_id uuid, p_answers jsonb, p_dietary jsonb, p_consent boolean
)
returns text
language sql
as $$
  select format(
    'select to_jsonb(r) from public.complete_confirmation_session(%L::uuid, %L, %L::uuid, %L::jsonb, %L::jsonb, %L::boolean) r',
    p_menu_id, p_hash, p_request_id, p_answers, p_dietary, p_consent
  );
$$;

-- 料理集合×アレルゲン集合の全組の回答配列
create function pg_temp.aa(p_dishes uuid[], p_items integer[], p_answer text default 'contains')
returns jsonb
language sql
as $$
  select coalesce(jsonb_agg(jsonb_build_object('dish_id', d, 'allergen_id', i, 'answer', p_answer) order by d, i), '[]'::jsonb)
    from unnest(p_dishes) as d, unnest(p_items) as i;
$$;

-- 料理集合×食事制限集合の全組の回答配列
create function pg_temp.da(p_dishes uuid[], p_items integer[], p_answer text default 'supported')
returns jsonb
language sql
as $$
  select coalesce(jsonb_agg(jsonb_build_object('dish_id', d, 'dietary_restriction_id', i, 'answer', p_answer) order by d, i), '[]'::jsonb)
    from unnest(p_dishes) as d, unnest(p_items) as i;
$$;

create function pg_temp.dish_id(p_menu_id uuid, p_position integer)
returns uuid
language sql
as $$ select d.id from public.dishes d where d.menu_id = p_menu_id and d.position = p_position; $$;

create function pg_temp.dish_ids(p_menu_id uuid, p_from integer, p_to integer)
returns uuid[]
language sql
as $$
  select array_agg(d.id order by d.position)
    from public.dishes d
   where d.menu_id = p_menu_id and d.position between p_from and p_to;
$$;

-- ---------------------------------------------------------------------------
\echo '[1/8] schema: tables, columns, RLS, views, functions, triggers, indexes'
-- ---------------------------------------------------------------------------

do $$
declare
  v_expected_columns constant jsonb := '{
    "restaurants": ["id uuid NN", "google_place_id text NN", "created_at timestamp with time zone NN"],
    "menus": ["id uuid NN", "restaurant_id uuid NULL", "user_publish_consent boolean NN", "image_path text NN",
              "analysis_token_hash text NN", "analysis_expires_at timestamp with time zone NN",
              "created_at timestamp with time zone NN"],
    "dishes": ["id uuid NN", "menu_id uuid NN", "name text NN", "position smallint NN", "name_key text NN",
               "translations jsonb NN", "price numeric(10,2) NULL", "currency character(3) NN", "version integer NN",
               "ai_result jsonb NN", "ai_model text NN", "prompt_version text NN",
               "analyzed_at timestamp with time zone NN", "created_at timestamp with time zone NN"],
    "allergens": ["id smallint NN", "code text NN", "name text NN", "name_en text NN", "category text NN",
                  "display_order smallint NN"],
    "dietary_restrictions": ["id smallint NN", "code text NN", "name text NN", "name_en text NN"],
    "confirmation_sessions": ["id uuid NN", "menu_id uuid NN", "restaurant_id uuid NULL", "request_id uuid NN",
                              "publish_consent boolean NN", "created_at timestamp with time zone NN"],
    "confirmation_answers": ["id uuid NN", "session_id uuid NN", "dish_id uuid NN", "allergen_id smallint NN",
                             "dish_version integer NN", "answer text NN", "created_at timestamp with time zone NN"],
    "confirmation_dietary_answers": ["id uuid NN", "session_id uuid NN", "dish_id uuid NN",
                                     "dietary_restriction_id smallint NN", "dish_version integer NN", "answer text NN",
                                     "created_at timestamp with time zone NN"],
    "published_menus": ["menu_id", "restaurant_id", "google_place_id", "scanned_at", "published_at", "dish_id",
                        "dish_name", "name_key", "translations", "price", "currency", "dish_version", "ai_result"],
    "published_confirmation_answers": ["session_id", "restaurant_id", "google_place_id", "menu_id", "dish_id",
                                       "name_key", "dish_version", "allergen_id", "answer", "confirmed_at"],
    "published_dietary_answers": ["session_id", "restaurant_id", "google_place_id", "menu_id", "dish_id",
                                  "name_key", "dish_version", "dietary_restriction_id", "answer", "confirmed_at"]
  }';
  v_table text;
  v_actual jsonb;
begin
  perform pg_temp.assert(
    (select array_agg(c.relname::text order by c.relname)
       from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relkind = 'r')
    = array['allergens', 'confirmation_answers', 'confirmation_dietary_answers', 'confirmation_sessions',
            'dietary_restrictions', 'dishes', 'menus', 'restaurants'],
    'public has exactly the 8 P0 tables');

  perform pg_temp.assert(
    not exists (select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
                 where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity),
    'RLS enabled on all tables');

  perform pg_temp.assert(
    not exists (select 1 from pg_policies p where p.schemaname = 'public'),
    'no RLS policies in public');

  perform pg_temp.assert(
    (select array_agg(c.relname::text order by c.relname)
       from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relkind in ('v', 'm'))
    = array['published_confirmation_answers', 'published_dietary_answers', 'published_menus'],
    'public has exactly the 3 public views');

  perform pg_temp.assert(
    not exists (select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
                 where n.nspname = 'public' and c.relkind = 'v'
                   and not coalesce(c.reloptions @> array['security_invoker=true'], false)),
    'all views use security_invoker=true');

  for v_table in select jsonb_object_keys(v_expected_columns) loop
    select jsonb_agg(
             case when c.relkind = 'r'
                  then format('%s %s %s', a.attname, format_type(a.atttypid, a.atttypmod),
                              case when a.attnotnull then 'NN' else 'NULL' end)
                  else a.attname::text end
             order by a.attnum)
      into v_actual
      from pg_attribute a
      join pg_class c on c.oid = a.attrelid
      join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relname = v_table and a.attnum > 0 and not a.attisdropped;
    perform pg_temp.assert(v_actual = v_expected_columns -> v_table,
      format('columns of %s: expected %s, got %s', v_table, v_expected_columns -> v_table, v_actual));
  end loop;

  perform pg_temp.assert(
    not exists (select 1 from pg_attribute a join pg_class c on c.oid = a.attrelid
                  join pg_namespace n on n.oid = c.relnamespace
                 where n.nspname = 'public' and c.relkind = 'v'
                   and a.attname in ('image_path', 'analysis_token_hash', 'account_id', 'user_publish_consent')),
    'views exclude image path, token hash and owner');

  perform pg_temp.assert(
    (select array_agg(format('%s(%s)', p.proname, pg_get_function_identity_arguments(p.oid)) order by p.proname)
       from pg_proc p join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = 'public')
    = array[
        'complete_confirmation_session(p_menu_id uuid, p_analysis_token_hash text, p_request_id uuid, p_answers jsonb, p_dietary_answers jsonb, p_publish_consent boolean, OUT session_id uuid, OUT confirmed_at timestamp with time zone, OUT replayed boolean)',
        'reject_snapshot_update()',
        'save_menu_analysis(p_restaurant_id uuid, p_image_path text, p_analysis_token_hash text, p_dishes jsonb, p_ai_model text, p_prompt_version text, p_analysis_expires_at timestamp with time zone)',
        'validate_confirmation_answer()',
        'validate_confirmation_session()'
      ],
    'public functions: 2 RPCs (single signature each) + 3 trigger functions');

  perform pg_temp.assert(
    not exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                 where n.nspname = 'public' and p.prosecdef),
    'all functions are security invoker');

  perform pg_temp.assert(
    (select array_agg(format('%s.%s:%s', c.relname, t.tgname, p.proname) order by c.relname, t.tgname)
       from pg_trigger t
       join pg_class c on c.oid = t.tgrelid
       join pg_namespace n on n.oid = c.relnamespace
       join pg_proc p on p.oid = t.tgfoid
      where n.nspname = 'public' and not t.tgisinternal)
    = array[
        'confirmation_answers.trg_answer_immutable:reject_snapshot_update',
        'confirmation_answers.trg_validate_answer:validate_confirmation_answer',
        'confirmation_dietary_answers.trg_dietary_answer_immutable:reject_snapshot_update',
        'confirmation_dietary_answers.trg_validate_dietary_answer:validate_confirmation_answer',
        'confirmation_sessions.trg_session_immutable:reject_snapshot_update',
        'confirmation_sessions.trg_validate_session:validate_confirmation_session',
        'dishes.trg_dish_immutable:reject_snapshot_update',
        'menus.trg_menu_immutable:reject_snapshot_update'
      ],
    'triggers match spec');

  perform pg_temp.assert(
    (select count(*) from pg_indexes i
      where i.schemaname = 'public'
        and i.indexname in ('idx_menus_restaurant', 'idx_dishes_menu', 'idx_dishes_name_key', 'idx_sessions_menu',
                            'idx_sessions_restaurant', 'idx_answers_dish_allergen_date',
                            'idx_dietary_answers_dish_item_date')) = 7,
    'P0 indexes exist');

  perform pg_temp.assert(
    (select indexdef from pg_indexes where indexname = 'idx_answers_dish_allergen_date')
      like '%(dish_id, allergen_id, created_at DESC)%'
    and (select indexdef from pg_indexes where indexname = 'idx_dietary_answers_dish_item_date')
      like '%(dish_id, dietary_restriction_id, created_at DESC)%',
    'answer indexes are ordered by created_at desc');

  -- 一意制約・外部キーの削除動作
  perform pg_temp.assert(
    (select array_agg(pg_get_constraintdef(co.oid) order by pg_get_constraintdef(co.oid))
       from pg_constraint co where co.contype = 'u' and co.connamespace = 'public'::regnamespace)
    = (select array_agg(x order by x) from unnest(array[
        'UNIQUE (analysis_token_hash)', 'UNIQUE (code)', 'UNIQUE (code)', 'UNIQUE (display_order)',
        'UNIQUE (google_place_id)', 'UNIQUE (image_path)', 'UNIQUE (menu_id, "position")',
        'UNIQUE (menu_id, request_id)', 'UNIQUE (name)', 'UNIQUE (session_id, dish_id, allergen_id)',
        'UNIQUE (session_id, dish_id, dietary_restriction_id)']) as x),
    'unique constraints match spec');

  perform pg_temp.assert(
    (select pg_get_constraintdef(co.oid) from pg_constraint co
      where co.conrelid = 'public.menus'::regclass and co.contype = 'f')
    = 'FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE RESTRICT',
    'menus.restaurant_id FK is ON DELETE RESTRICT');

  perform pg_temp.assert(
    (select count(*) from pg_constraint co where co.contype = 'f' and co.connamespace = 'public'::regnamespace) = 10,
    '10 foreign keys');
end;
$$;

-- ---------------------------------------------------------------------------
\echo '[2/8] master data: 29 allergens (9 + 20) and 4 dietary restrictions'
-- ---------------------------------------------------------------------------

do $$
begin
  perform pg_temp.assert((
    with expected (id, code, name, name_en, category, display_order) as (values
       (1::smallint, 'egg', '卵', 'Egg', 'required', 1::smallint),
       (2, 'milk', '乳', 'Milk', 'required', 2),
       (3, 'wheat', '小麦', 'Wheat', 'required', 3),
       (6, 'buckwheat', 'そば', 'Buckwheat', 'required', 4),
       (7, 'peanut', '落花生（ピーナッツ）', 'Peanut', 'required', 5),
       (4, 'shrimp', 'えび', 'Shrimp', 'required', 6),
       (5, 'crab', 'かに', 'Crab', 'required', 7),
       (8, 'walnut', 'くるみ', 'Walnut', 'required', 8),
       (11, 'cashew', 'カシューナッツ', 'Cashew', 'required', 9),
       (12, 'almond', 'アーモンド', 'Almond', 'recommended', 10),
       (13, 'abalone', 'あわび', 'Abalone', 'recommended', 11),
       (14, 'squid', 'いか', 'Squid', 'recommended', 12),
       (15, 'salmon_roe', 'いくら', 'Salmon roe', 'recommended', 13),
       (16, 'orange', 'オレンジ', 'Orange', 'recommended', 14),
       (17, 'kiwi', 'キウイフルーツ', 'Kiwi', 'recommended', 15),
       (18, 'beef', '牛肉', 'Beef', 'recommended', 16),
       (10, 'sesame', 'ごま', 'Sesame', 'recommended', 17),
       (19, 'salmon', 'さけ', 'Salmon', 'recommended', 18),
       (20, 'mackerel', 'さば', 'Mackerel', 'recommended', 19),
       (9, 'soy', '大豆', 'Soy', 'recommended', 20),
       (21, 'chicken', '鶏肉', 'Chicken', 'recommended', 21),
       (22, 'banana', 'バナナ', 'Banana', 'recommended', 22),
       (23, 'pork', '豚肉', 'Pork', 'recommended', 23),
       (24, 'pistachio', 'ピスタチオ', 'Pistachio', 'recommended', 24),
       (25, 'macadamia_nut', 'マカダミアナッツ', 'Macadamia nut', 'recommended', 25),
       (26, 'peach', 'もも', 'Peach', 'recommended', 26),
       (27, 'yam', 'やまいも', 'Yam', 'recommended', 27),
       (28, 'apple', 'りんご', 'Apple', 'recommended', 28),
       (29, 'gelatin', 'ゼラチン', 'Gelatin', 'recommended', 29)
    )
    select not exists (
      (select id, code, name, name_en, category, display_order from public.allergens
       except select * from expected)
      union all
      (select * from expected
       except select id, code, name, name_en, category, display_order from public.allergens))
  ), 'allergens match the spec exactly (both directions)');

  perform pg_temp.assert((select count(*) from public.allergens) = 29, '29 allergens');
  perform pg_temp.assert((select count(*) from public.allergens where category = 'required') = 9, '9 required');
  perform pg_temp.assert((select count(*) from public.allergens where category = 'recommended') = 20, '20 recommended');
  perform pg_temp.assert(
    (select array_agg(display_order order by display_order) from public.allergens)
    = (select array_agg(i::smallint order by i) from generate_series(1, 29) as i),
    'display_order is 1..29');
  perform pg_temp.assert(
    (select array_agg(id order by id) from public.allergens)
    = (select array_agg(i::smallint order by i) from generate_series(1, 29) as i),
    'allergen ids are 1..29');
  perform pg_temp.assert(
    (select array_agg(code order by id) from public.allergens where id <= 10)
    = array['egg', 'milk', 'wheat', 'shrimp', 'crab', 'buckwheat', 'peanut', 'walnut', 'soy', 'sesame'],
    'legacy allergen ids 1..10 keep their codes');
  perform pg_temp.assert(
    (select array_agg(format('%s:%s:%s:%s', id, code, name, name_en) order by id) from public.dietary_restrictions)
    = array['1:vegan:ヴィーガン:Vegan', '2:vegetarian:ベジタリアン:Vegetarian', '3:halal:ハラール:Halal',
            '4:no_alcohol:アルコール不使用:No alcohol'],
    'dietary restrictions match spec');
end;
$$;

-- ---------------------------------------------------------------------------
\echo '[3/8] privileges: PUBLIC/anon/authenticated have nothing, service_role matches spec'
-- ---------------------------------------------------------------------------

do $$
declare
  v_role text;
begin
  foreach v_role in array array['anon', 'authenticated'] loop
    perform pg_temp.assert(
      not exists (select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
                   where n.nspname = 'public' and c.relkind in ('r', 'v')
                     and (has_table_privilege(v_role, c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                          or has_any_column_privilege(v_role, c.oid, 'SELECT,INSERT,UPDATE,REFERENCES'))),
      format('%s has no table/view/column privileges', v_role));
    perform pg_temp.assert(
      not exists (select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
                   where n.nspname = 'public'
                     and case when c.relkind = 'S'
                              then has_sequence_privilege(v_role, c.oid, 'USAGE,SELECT,UPDATE')
                              else false end),
      format('%s has no sequence privileges', v_role));
    perform pg_temp.assert(
      not exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                   where n.nspname = 'public' and has_function_privilege(v_role, p.oid, 'EXECUTE')),
      format('%s cannot execute any public function', v_role));
  end loop;

  -- PUBLIC（grantee 0）への付与がないこと
  perform pg_temp.assert(
    not exists (select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace,
                 lateral aclexplode(c.relacl) as acl
                where n.nspname = 'public' and acl.grantee = 0),
    'PUBLIC has no relation privileges');
  perform pg_temp.assert(
    not exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                 where n.nspname = 'public' and (p.proacl is null
                   or exists (select 1 from aclexplode(p.proacl) as acl where acl.grantee = 0))),
    'PUBLIC has no function privileges (explicit ACL on every function)');

  -- service_role のテーブル・ビュー権限が正本の表と一致すること
  perform pg_temp.assert(
    (select array_agg(format('%s:%s', c.relname, acl.privilege_type) order by c.relname, acl.privilege_type)
       from pg_class c join pg_namespace n on n.oid = c.relnamespace,
            lateral aclexplode(c.relacl) as acl
      where n.nspname = 'public' and acl.grantee = 'service_role'::regrole)
    = array[
        'allergens:SELECT',
        'confirmation_answers:INSERT', 'confirmation_answers:SELECT',
        'confirmation_dietary_answers:INSERT', 'confirmation_dietary_answers:SELECT',
        'confirmation_sessions:INSERT', 'confirmation_sessions:SELECT',
        'dietary_restrictions:SELECT',
        'dishes:INSERT', 'dishes:SELECT',
        'menus:INSERT', 'menus:SELECT',
        'published_confirmation_answers:SELECT',
        'published_dietary_answers:SELECT',
        'published_menus:SELECT',
        'restaurants:INSERT', 'restaurants:SELECT'
      ],
    'service_role relation privileges match spec');

  perform pg_temp.assert(
    (select array_agg(format('%s.%s:%s', c.relname, a.attname, acl.privilege_type))
       from pg_attribute a
       join pg_class c on c.oid = a.attrelid
       join pg_namespace n on n.oid = c.relnamespace,
            lateral aclexplode(a.attacl) as acl
      where n.nspname = 'public' and acl.grantee = 'service_role'::regrole)
    = array['menus.id:UPDATE'],
    'service_role column privilege is only UPDATE(menus.id)');

  perform pg_temp.assert(
    (select array_agg(p.proname::text order by p.proname)
       from pg_proc p join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = 'public' and has_function_privilege('service_role', p.oid, 'EXECUTE'))
    = array['complete_confirmation_session', 'save_menu_analysis'],
    'service_role executes only the 2 RPCs');
end;
$$;

-- 実際の操作が拒否されること（anon・authenticated）
do $$
declare
  v_role text;
  v_rel text;
begin
  foreach v_role in array array['anon', 'authenticated'] loop
    foreach v_rel in array array['restaurants', 'menus', 'dishes', 'allergens', 'dietary_restrictions',
                                 'confirmation_sessions', 'confirmation_answers', 'confirmation_dietary_answers',
                                 'published_menus', 'published_confirmation_answers', 'published_dietary_answers'] loop
      perform pg_temp.expect_error(v_role, format('select 1 from public.%I limit 1', v_rel), '42501');
    end loop;
    perform pg_temp.expect_error(v_role,
      $q$insert into public.restaurants (google_place_id) values ('verify-anon')$q$, '42501');
    perform pg_temp.expect_error(v_role,
      $q$update public.menus set user_publish_consent = true$q$, '42501');
    perform pg_temp.expect_error(v_role, $q$delete from public.menus$q$, '42501');
    perform pg_temp.expect_error(v_role,
      pg_temp.save_sql(null, 'verify/anon.jpg', pg_temp.h('anon'), pg_temp.dishes(1)), '42501');
    perform pg_temp.expect_error(v_role,
      pg_temp.confirm_sql(gen_random_uuid(), pg_temp.h('anon'), gen_random_uuid(), '[]', '[]', false), '42501');
  end loop;
end;
$$;

-- ---------------------------------------------------------------------------
\echo '[4/8] save_menu_analysis: normal save, order, defaults, rejection without partial rows'
-- ---------------------------------------------------------------------------

do $$
declare
  v_restaurant_id uuid;
  v_menu_id uuid;
  v_menu public.menus%rowtype;
  v_menus_before bigint;
begin
  v_restaurant_id := (pg_temp.exec_as('service_role',
    $q$with r as (insert into public.restaurants (google_place_id) values ('verify-place-a') returning id)
       select to_jsonb(r.id) from r$q$) #>> '{}')::uuid;
  perform pg_temp.put('restaurant_a', v_restaurant_id::text);

  -- メニューA：店舗あり・3料理。配列順に position を保存し、currency 省略時は JPY、price は null を保持する。
  v_menu_id := (pg_temp.exec_as('service_role', pg_temp.save_sql(
    v_restaurant_id, 'verify/a.jpg', pg_temp.h('token-a'),
    jsonb_build_array(pg_temp.dish('Shrimp tempura soba', 1200),
                      pg_temp.dish('Kitsune udon', null, false),
                      pg_temp.dish('Katsu curry', 980.5)))) #>> '{}')::uuid;
  perform pg_temp.put('menu_a', v_menu_id::text);

  select * into v_menu from public.menus where id = v_menu_id;
  perform pg_temp.assert(v_menu.restaurant_id = v_restaurant_id, 'menu A restaurant');
  perform pg_temp.assert(v_menu.user_publish_consent = false, 'P0 save sets user_publish_consent=false');
  perform pg_temp.assert(v_menu.analysis_token_hash = pg_temp.h('token-a'), 'token hash stored as given');
  perform pg_temp.assert(v_menu.analysis_expires_at = v_menu.created_at + interval '24 hours',
    'default expiry is 24 hours after creation');
  perform pg_temp.assert(
    (select array_agg(format('%s:%s:%s:%s:%s', position, name, coalesce(price::text, 'null'), currency, version)
                      order by position)
       from public.dishes where menu_id = v_menu_id)
    = array['1:Shrimp tempura soba:1200.00:JPY:1', '2:Kitsune udon:null:JPY:1', '3:Katsu curry:980.50:JPY:1'],
    'dishes saved in array order with position 1..3, defaults applied');
  perform pg_temp.assert(
    (select bool_and(ai_model = 'gemini-test' and prompt_version = 'v4'
                     and translations #>> '{en,name}' = name and jsonb_typeof(ai_result) = 'object')
       from public.dishes where menu_id = v_menu_id),
    'ai_model, prompt_version, translations, ai_result stored');

  -- メニューB：店舗あり・12料理（上限・11料理の検証用）
  v_menu_id := (pg_temp.exec_as('service_role', pg_temp.save_sql(
    v_restaurant_id, 'verify/b.jpg', pg_temp.h('token-b'), pg_temp.dishes(12))) #>> '{}')::uuid;
  perform pg_temp.put('menu_b', v_menu_id::text);

  -- ゲストメニューG：店舗未選択・2料理
  v_menu_id := (pg_temp.exec_as('service_role', pg_temp.save_sql(
    null, 'verify/g.jpg', pg_temp.h('token-g'), pg_temp.dishes(2))) #>> '{}')::uuid;
  perform pg_temp.put('menu_g', v_menu_id::text);
  perform pg_temp.assert(
    (select restaurant_id is null and not user_publish_consent from public.menus where id = v_menu_id),
    'guest menu has no restaurant and consent false');

  -- メニューL：5回上限の検証用（20料理の上限ちょうど）
  v_menu_id := (pg_temp.exec_as('service_role', pg_temp.save_sql(
    v_restaurant_id, 'verify/l.jpg', pg_temp.h('token-l'), pg_temp.dishes(20))) #>> '{}')::uuid;
  perform pg_temp.put('menu_l', v_menu_id::text);
  perform pg_temp.assert((select count(*) from public.dishes where menu_id = v_menu_id) = 20, '20 dishes accepted');

  -- 拒否されるケース。いずれもメニュー・料理を残さない。
  select count(*) into v_menus_before from public.menus;

  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('x0'), '[]'), '22023', 'dishes_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('x21'), pg_temp.dishes(21)), '22023', 'dishes_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('x'), '{"name":"x"}'), '22023', 'dishes_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('x'), null), '22023', 'dishes_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('x'), '["dish"]'), '22023', 'dishes_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('x'),
      jsonb_build_array(pg_temp.dish('A') || '{"extra":1}')), '22023', 'dishes_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('x'),
      jsonb_build_array(pg_temp.dish('A') - 'name')), '22023', 'dishes_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('x'),
      jsonb_build_array(pg_temp.dish('A') || '{"ai_result":[]}')), '22023', 'dishes_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('x'),
      jsonb_build_array(pg_temp.dish('A') || '{"price":"1200"}')), '22023', 'dishes_invalid');
  -- 不正なトークンハッシュ（大文字・短い・null）
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', upper(pg_temp.h('x')), pg_temp.dishes(1)),
    '22023', 'invalid_analysis_token_hash');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', left(pg_temp.h('x'), 63), pg_temp.dishes(1)),
    '22023', 'invalid_analysis_token_hash');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', null, pg_temp.dishes(1)),
    '22023', 'invalid_analysis_token_hash');
  -- メニュー登録後の料理で失敗：2件目の料理名が201文字・負の価格 → メニューも含めて戻る
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('x'),
      jsonb_build_array(pg_temp.dish('ok'), pg_temp.dish(repeat('x', 201)))), '23514');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('x'),
      jsonb_build_array(pg_temp.dish('ok'), pg_temp.dish('neg', -1))), '23514');
  -- 存在しない店舗、重複した画像パス・トークンハッシュ、過去の期限
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(gen_random_uuid(), 'verify/x.jpg', pg_temp.h('x'), pg_temp.dishes(1)), '23503');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/a.jpg', pg_temp.h('x'), pg_temp.dishes(1)), '23505');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('token-a'), pg_temp.dishes(1)), '23505');
  perform pg_temp.expect_error('service_role',
    pg_temp.save_sql(v_restaurant_id, 'verify/x.jpg', pg_temp.h('x'), pg_temp.dishes(1), now() - interval '1 second'),
    '23514');

  perform pg_temp.assert((select count(*) from public.menus) = v_menus_before, 'rejected saves left no menus');
  perform pg_temp.assert(not exists (select 1 from public.menus where image_path = 'verify/x.jpg'),
    'rejected saves left no partial menu');
end;
$$;

-- ---------------------------------------------------------------------------
\echo '[5/8] complete_confirmation_session: allergen-only, dietary-only, both, replay, conflicts'
-- ---------------------------------------------------------------------------

do $$
declare
  v_menu_a uuid := pg_temp.get('menu_a')::uuid;
  v_hash_a text := pg_temp.h('token-a');
  a1 uuid := pg_temp.dish_id(pg_temp.get('menu_a')::uuid, 1);
  a2 uuid := pg_temp.dish_id(pg_temp.get('menu_a')::uuid, 2);
  a3 uuid := pg_temp.dish_id(pg_temp.get('menu_a')::uuid, 3);
  v_result jsonb;
  v_replay jsonb;
  v_r3 uuid := gen_random_uuid();
  v_answers jsonb;
  v_dietary jsonb;
  v_session_id uuid;
  v_rows bigint;
begin
  perform pg_temp.put('a1', a1::text);

  -- アレルゲンのみ（店員同意あり）
  v_result := pg_temp.exec_as('service_role', pg_temp.confirm_sql(
    v_menu_a, v_hash_a, gen_random_uuid(), pg_temp.aa(array[a1], array[4, 6]), '[]', true));
  perform pg_temp.assert((v_result ->> 'replayed')::boolean = false, 'allergen-only: replayed=false');
  v_session_id := (v_result ->> 'session_id')::uuid;
  perform pg_temp.put('session_1', v_session_id::text);
  perform pg_temp.assert(
    (select publish_consent and restaurant_id = pg_temp.get('restaurant_a')::uuid
            and created_at = (v_result ->> 'confirmed_at')::timestamptz
       from public.confirmation_sessions where id = v_session_id),
    'allergen-only: session stores staff consent, restaurant from menu, confirmed_at');
  perform pg_temp.assert(
    (select count(*) from public.confirmation_answers where session_id = v_session_id and dish_version = 1) = 2
    and (select count(*) from public.confirmation_dietary_answers where session_id = v_session_id) = 0,
    'allergen-only: 2 allergen answers, no dietary rows');

  -- 食事制限のみ（不同意・unknown を含む）
  v_dietary := jsonb_build_array(
    jsonb_build_object('dish_id', a2, 'dietary_restriction_id', 1, 'answer', 'not_supported'),
    jsonb_build_object('dish_id', a2, 'dietary_restriction_id', 4, 'answer', 'unknown'));
  v_result := pg_temp.exec_as('service_role', pg_temp.confirm_sql(
    v_menu_a, v_hash_a, gen_random_uuid(), '[]', v_dietary, false));
  v_session_id := (v_result ->> 'session_id')::uuid;
  perform pg_temp.assert(
    (select not publish_consent from public.confirmation_sessions where id = v_session_id),
    'dietary-only: staff non-consent kept');
  perform pg_temp.assert(
    (select array_agg(format('%s:%s', dietary_restriction_id, answer) order by dietary_restriction_id)
       from public.confirmation_dietary_answers where session_id = v_session_id)
    = array['1:not_supported', '4:unknown']
    and not exists (select 1 from public.confirmation_answers where session_id = v_session_id),
    'dietary-only: explicit unknown saved, no allergen rows');

  -- 両方（料理集合 {a1, a3} が一致）
  v_answers := jsonb_build_array(
    jsonb_build_object('dish_id', a1, 'allergen_id', 1, 'answer', 'contains'),
    jsonb_build_object('dish_id', a1, 'allergen_id', 2, 'answer', 'unknown'),
    jsonb_build_object('dish_id', a3, 'allergen_id', 1, 'answer', 'not_contains'),
    jsonb_build_object('dish_id', a3, 'allergen_id', 2, 'answer', 'cross_contact'));
  v_dietary := pg_temp.da(array[a1, a3], array[3], 'unknown');
  v_result := pg_temp.exec_as('service_role', pg_temp.confirm_sql(
    v_menu_a, v_hash_a, v_r3, v_answers, v_dietary, false));
  v_session_id := (v_result ->> 'session_id')::uuid;
  perform pg_temp.assert((v_result ->> 'replayed')::boolean = false, 'both: replayed=false');
  perform pg_temp.assert(
    (select count(*) from public.confirmation_answers where session_id = v_session_id) = 4
    and (select count(*) from public.confirmation_dietary_answers where session_id = v_session_id) = 2
    and (select answer from public.confirmation_answers
          where session_id = v_session_id and dish_id = a1 and allergen_id = 2) = 'unknown',
    'both: 4 allergen + 2 dietary answers, unknown kept');

  select count(*) into v_rows from public.confirmation_sessions where menu_id = v_menu_a;
  perform pg_temp.assert(v_rows = 3, 'menu A has 3 sessions');

  -- 並び替え・大文字UUIDの再送は同じ確認を返し、行を増やさない
  v_replay := pg_temp.exec_as('service_role', pg_temp.confirm_sql(
    v_menu_a, v_hash_a, v_r3,
    (select jsonb_agg(e order by e ->> 'allergen_id' desc, e ->> 'dish_id' desc)
       from jsonb_array_elements(v_answers) as e),
    (select jsonb_agg(jsonb_set(e, '{dish_id}', to_jsonb(upper(e ->> 'dish_id'))) order by e ->> 'dish_id' desc)
       from jsonb_array_elements(v_dietary) as e),
    false));
  perform pg_temp.assert((v_replay ->> 'replayed')::boolean, 'reordered resend: replayed=true');
  perform pg_temp.assert(v_replay ->> 'session_id' = v_result ->> 'session_id'
                         and v_replay ->> 'confirmed_at' = v_result ->> 'confirmed_at',
    'reordered resend returns the existing session and confirmed_at');
  perform pg_temp.assert(
    (select count(*) from public.confirmation_sessions where menu_id = v_menu_a) = 3
    and (select count(*) from public.confirmation_answers where session_id = v_session_id) = 4
    and (select count(*) from public.confirmation_dietary_answers where session_id = v_session_id) = 2,
    'reordered resend adds no rows');

  -- 同じ request_id で内容・店員同意を変えると競合
  perform pg_temp.expect_error('service_role', pg_temp.confirm_sql(
    v_menu_a, v_hash_a, v_r3, jsonb_set(v_answers, '{0,answer}', '"not_contains"'), v_dietary, false),
    '40001', 'request_id_conflict');
  perform pg_temp.expect_error('service_role', pg_temp.confirm_sql(
    v_menu_a, v_hash_a, v_r3, v_answers, jsonb_set(v_dietary, '{0,answer}', '"supported"'), false),
    '40001', 'request_id_conflict');
  perform pg_temp.expect_error('service_role', pg_temp.confirm_sql(
    v_menu_a, v_hash_a, v_r3, v_answers, v_dietary, true),
    '40001', 'request_id_conflict');
  perform pg_temp.expect_error('service_role', pg_temp.confirm_sql(
    v_menu_a, v_hash_a, v_r3, v_answers, '[]', false),
    '40001', 'request_id_conflict');

  -- 50回答・10料理ちょうどは成功（メニューB：10料理×アレルゲン4＋10料理×食事制限1）
  v_result := pg_temp.exec_as('service_role', pg_temp.confirm_sql(
    pg_temp.get('menu_b')::uuid, pg_temp.h('token-b'), gen_random_uuid(),
    pg_temp.aa(pg_temp.dish_ids(pg_temp.get('menu_b')::uuid, 1, 10), array[1, 2, 3, 4]),
    pg_temp.da(pg_temp.dish_ids(pg_temp.get('menu_b')::uuid, 1, 10), array[2]),
    false));
  perform pg_temp.assert(
    (select count(*) from public.confirmation_answers where session_id = (v_result ->> 'session_id')::uuid) = 40
    and (select count(*) from public.confirmation_dietary_answers
          where session_id = (v_result ->> 'session_id')::uuid) = 10,
    '50 answers over 10 dishes accepted');
end;
$$;

-- ---------------------------------------------------------------------------
\echo '[6/8] complete_confirmation_session: validation errors leave nothing behind'
-- ---------------------------------------------------------------------------

do $$
declare
  v_menu_a uuid := pg_temp.get('menu_a')::uuid;
  v_menu_b uuid := pg_temp.get('menu_b')::uuid;
  v_hash_a text := pg_temp.h('token-a');
  v_hash_b text := pg_temp.h('token-b');
  a1 uuid := pg_temp.dish_id(pg_temp.get('menu_a')::uuid, 1);
  a2 uuid := pg_temp.dish_id(pg_temp.get('menu_a')::uuid, 2);
  g1 uuid := pg_temp.dish_id(pg_temp.get('menu_g')::uuid, 1);
  v_sessions bigint;
  v_answers bigint;
  v_dietary bigint;
  v_ok jsonb := pg_temp.aa(array[pg_temp.dish_id(pg_temp.get('menu_a')::uuid, 1)], array[4]);
begin
  select count(*) into v_sessions from public.confirmation_sessions;
  select count(*) into v_answers from public.confirmation_answers;
  select count(*) into v_dietary from public.confirmation_dietary_answers;

  -- 両方空・null・配列以外
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), '[]', '[]', true), '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), null, '[]', true), '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), v_ok, null, true), '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), '{}', '[]', true), '22023', 'answers_invalid');
  -- request_id・店員同意の欠落
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, null, v_ok, '[]', true), '22023', 'validation_error');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), v_ok, '[]', null), '22023', 'validation_error');
  -- 51回答（3料理×17アレルゲン）
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_b, v_hash_b, gen_random_uuid(),
      pg_temp.aa(pg_temp.dish_ids(v_menu_b, 1, 3), (select array_agg(i) from generate_series(1, 17) as i)), '[]', true),
    '22023', 'answers_invalid');
  -- 51回答（アレルゲン50＋食事制限1の合計）
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_b, v_hash_b, gen_random_uuid(),
      pg_temp.aa(pg_temp.dish_ids(v_menu_b, 1, 2), (select array_agg(i) from generate_series(1, 25) as i)),
      pg_temp.da(pg_temp.dish_ids(v_menu_b, 1, 1), array[1]), true),
    '22023', 'answers_invalid');
  -- 料理11件
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_b, v_hash_b, gen_random_uuid(),
      pg_temp.aa(pg_temp.dish_ids(v_menu_b, 1, 11), array[4]), '[]', true),
    '22023', 'answers_invalid');
  -- 未知のID（アレルゲン30・0、食事制限5）、別ID空間の取り違え
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), pg_temp.aa(array[a1], array[30]), '[]', true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), pg_temp.aa(array[a1], array[0]), '[]', true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), '[]', pg_temp.da(array[a1], array[5]), true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), '[]', pg_temp.da(array[a1], array[1], 'contains'), true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), pg_temp.aa(array[a1], array[4], 'supported'), '[]', true),
    '22023', 'answers_invalid');
  -- 重複
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), v_ok || v_ok, '[]', true), '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(),
      v_ok || jsonb_build_array(jsonb_build_object('dish_id', a1, 'allergen_id', 4, 'answer', 'unknown'))
      || pg_temp.aa(array[a2], array[4]), '[]', true),
    '22023', 'answers_invalid');
  -- 直積不足（a1×{4,6}・a2×{4}）
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(),
      pg_temp.aa(array[a1], array[4, 6]) || pg_temp.aa(array[a2], array[4]), '[]', true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), '[]',
      pg_temp.da(array[a1, a2], array[1]) || pg_temp.da(array[a1], array[2]), true),
    '22023', 'answers_invalid');
  -- 両配列の料理集合の不一致
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(),
      pg_temp.aa(array[a1], array[4]), pg_temp.da(array[a2], array[1]), true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(),
      pg_temp.aa(array[a1, a2], array[4]), pg_temp.da(array[a1], array[1]), true),
    '22023', 'answers_invalid');
  -- 別メニューの料理・存在しない料理
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), pg_temp.aa(array[g1], array[4]), '[]', true),
    '22023', 'dish_not_in_menu');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(),
      pg_temp.aa(array[a1, g1], array[4]), pg_temp.da(array[a1, g1], array[1]), true),
    '22023', 'dish_not_in_menu');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), pg_temp.aa(array[gen_random_uuid()], array[4]), '[]', true),
    '22023', 'dish_not_in_menu');
  -- 欠落・null・不正値・未定義フィールド・型違い
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(),
      jsonb_build_array(jsonb_build_object('dish_id', a1, 'allergen_id', 4)), '[]', true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(),
      jsonb_build_array(jsonb_build_object('dish_id', a1, 'allergen_id', 4, 'answer', null)), '[]', true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(),
      jsonb_build_array(jsonb_build_object('dish_id', null, 'allergen_id', 4, 'answer', 'contains')), '[]', true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), '[]',
      jsonb_build_array(jsonb_build_object('dish_id', a1, 'dietary_restriction_id', 1, 'answer', null)), true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(),
      jsonb_build_array(jsonb_build_object('dish_id', a1, 'allergen_id', 4, 'answer', 'yes')), '[]', true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(),
      jsonb_build_array(jsonb_build_object('dish_id', a1, 'allergen_id', 4, 'answer', 'contains', 'dish_version', 1)),
      '[]', true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(),
      jsonb_build_array(jsonb_build_object('dish_id', a1, 'allergen_id', '4', 'answer', 'contains')), '[]', true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(),
      jsonb_build_array(jsonb_build_object('dish_id', 'not-a-uuid', 'allergen_id', 4, 'answer', 'contains')), '[]', true),
    '22023', 'answers_invalid');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, v_hash_a, gen_random_uuid(), '[null]', '[]', true), '22023', 'answers_invalid');

  perform pg_temp.assert(
    (select count(*) from public.confirmation_sessions) = v_sessions
    and (select count(*) from public.confirmation_answers) = v_answers
    and (select count(*) from public.confirmation_dietary_answers) = v_dietary,
    'rejected confirmations left no sessions or answers');
end;
$$;

-- ---------------------------------------------------------------------------
\echo '[7/8] tokens, expiry, 5-session limit, triggers, immutability, row lock'
-- ---------------------------------------------------------------------------

do $$
declare
  v_menu_a uuid := pg_temp.get('menu_a')::uuid;
  v_menu_l uuid := pg_temp.get('menu_l')::uuid;
  v_hash_a text := pg_temp.h('token-a');
  v_hash_l text := pg_temp.h('token-l');
  a1 uuid := pg_temp.get('a1')::uuid;
  l1 uuid := pg_temp.dish_id(pg_temp.get('menu_l')::uuid, 1);
  v_ok jsonb := pg_temp.aa(array[pg_temp.get('a1')::uuid], array[4]);
  v_requests uuid[] := array[gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), gen_random_uuid()];
  v_restaurant_id uuid := pg_temp.get('restaurant_a')::uuid;
  v_expired_menu uuid;
  v_expired_dish uuid;
  v_expired_request uuid := gen_random_uuid();
  v_result jsonb;
  i integer;
begin
  -- 解析用トークン：他メニューのトークン・不正なハッシュ・null、存在しないメニュー
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, pg_temp.h('token-b'), gen_random_uuid(), v_ok, '[]', true), '28000', 'invalid_analysis_token');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, upper(v_hash_a), gen_random_uuid(), v_ok, '[]', true), '28000', 'invalid_analysis_token');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, 'token-a', gen_random_uuid(), v_ok, '[]', true), '28000', 'invalid_analysis_token');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_a, null, gen_random_uuid(), v_ok, '[]', true), '28000', 'invalid_analysis_token');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(gen_random_uuid(), v_hash_a, gen_random_uuid(), v_ok, '[]', true), 'P0002', 'menu_not_found');

  -- 期限切れ：検証用に過去日時のメニュー・確認を管理者接続で直接作成する（RPCでは過去の作成日時を指定できないため）
  insert into public.menus (restaurant_id, image_path, analysis_token_hash, analysis_expires_at, created_at)
  values (v_restaurant_id, 'verify/expired.jpg', pg_temp.h('token-e'), now() - interval '1 day', now() - interval '2 days')
  returning id into v_expired_menu;
  insert into public.dishes (menu_id, name, position, name_key, translations, ai_result, ai_model, prompt_version)
  values (v_expired_menu, 'Old dish', 1, 'olddish', '{"en":{"name":"Old dish","description":""}}', '{}', 'gemini-test', 'v4')
  returning id into v_expired_dish;
  insert into public.confirmation_sessions (menu_id, restaurant_id, request_id, publish_consent)
  values (v_expired_menu, v_restaurant_id, v_expired_request, false);
  insert into public.confirmation_answers (session_id, dish_id, allergen_id, dish_version, answer)
  select s.id, v_expired_dish, 4, 1, 'contains' from public.confirmation_sessions s where s.request_id = v_expired_request;

  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_expired_menu, pg_temp.h('token-e'), gen_random_uuid(),
      pg_temp.aa(array[v_expired_dish], array[4]), '[]', false), 'P0003', 'analysis_expired');
  -- 期限切れの再送（既存と同内容）も拒否
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_expired_menu, pg_temp.h('token-e'), v_expired_request,
      pg_temp.aa(array[v_expired_dish], array[4]), '[]', false), 'P0003', 'analysis_expired');

  -- 5回の上限：5件まで成功、5件目の再送は成功、新規6件目は拒否
  for i in 1..5 loop
    v_result := pg_temp.exec_as('service_role', pg_temp.confirm_sql(
      v_menu_l, v_hash_l, v_requests[i], pg_temp.aa(array[l1], array[i]), '[]', false));
    perform pg_temp.assert((v_result ->> 'replayed')::boolean = false, format('limit: session %s created', i));
  end loop;
  v_result := pg_temp.exec_as('service_role', pg_temp.confirm_sql(
    v_menu_l, v_hash_l, v_requests[5], pg_temp.aa(array[l1], array[5]), '[]', false));
  perform pg_temp.assert((v_result ->> 'replayed')::boolean, 'limit: resend of 5th session succeeds after limit');
  v_result := pg_temp.exec_as('service_role', pg_temp.confirm_sql(
    v_menu_l, v_hash_l, v_requests[1], pg_temp.aa(array[l1], array[1]), '[]', false));
  perform pg_temp.assert((v_result ->> 'replayed')::boolean, 'limit: resend of 1st session succeeds after limit');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_l, v_hash_l, gen_random_uuid(), pg_temp.aa(array[l1], array[6]), '[]', false),
    '22023', 'confirmation_limit_reached');
  perform pg_temp.expect_error('service_role',
    pg_temp.confirm_sql(v_menu_l, v_hash_l, v_requests[5], pg_temp.aa(array[l1], array[6]), '[]', false),
    '40001', 'request_id_conflict');
  perform pg_temp.assert((select count(*) from public.confirmation_sessions where menu_id = v_menu_l) = 5,
    'limit: exactly 5 sessions');

  -- トリガー：RPCを経由しない挿入でも上限・店舗一致・料理の所属・版を検証する
  perform pg_temp.expect_error('service_role', format(
    'insert into public.confirmation_sessions (menu_id, restaurant_id, request_id, publish_consent) values (%L, %L, %L, false)',
    v_menu_l, v_restaurant_id, gen_random_uuid()), '22023', 'confirmation_limit_reached');
  perform pg_temp.expect_error('service_role', format(
    'insert into public.confirmation_sessions (menu_id, restaurant_id, request_id, publish_consent) values (%L, null, %L, false)',
    v_menu_a, gen_random_uuid()), '22023', 'restaurant_mismatch');
  perform pg_temp.expect_error('service_role', format(
    'insert into public.confirmation_answers (session_id, dish_id, allergen_id, dish_version, answer) values (%L, %L, 1, 2, %L)',
    pg_temp.get('session_1'), a1, 'contains'), '22023', 'dish_version_mismatch');
  perform pg_temp.expect_error('service_role', format(
    'insert into public.confirmation_dietary_answers (session_id, dish_id, dietary_restriction_id, dish_version, answer) values (%L, %L, 1, 2, %L)',
    pg_temp.get('session_1'), a1, 'supported'), '22023', 'dish_version_mismatch');
  perform pg_temp.expect_error('service_role', format(
    'insert into public.confirmation_answers (session_id, dish_id, allergen_id, dish_version, answer) values (%L, %L, 1, 1, %L)',
    pg_temp.get('session_1'), pg_temp.dish_id(pg_temp.get('menu_g')::uuid, 1), 'contains'), '22023', 'dish_not_in_menu');
  perform pg_temp.expect_error('service_role', format(
    'insert into public.confirmation_dietary_answers (session_id, dish_id, dietary_restriction_id, dish_version, answer) values (%L, %L, 1, 1, %L)',
    pg_temp.get('session_1'), pg_temp.dish_id(pg_temp.get('menu_g')::uuid, 1), 'supported'), '22023', 'dish_not_in_menu');

  -- service_role の行ロックは成功し、スナップショットの更新・削除は拒否される
  v_result := pg_temp.exec_as('service_role', format(
    'select to_jsonb(count(*)) from (select id from public.menus where id = %L for update) as x', v_menu_a));
  perform pg_temp.assert(v_result = '1'::jsonb, 'service_role can lock a menu row FOR UPDATE');
  perform pg_temp.expect_error('service_role',
    format('update public.menus set id = id where id = %L', v_menu_a), '55000', 'snapshot_is_immutable');
  perform pg_temp.expect_error('service_role',
    format('update public.menus set user_publish_consent = true where id = %L', v_menu_a), '42501');
  perform pg_temp.expect_error('service_role',
    format('update public.menus set analysis_expires_at = now() where id = %L', v_menu_a), '42501');
  perform pg_temp.expect_error('service_role', 'update public.dishes set name = name', '42501');
  perform pg_temp.expect_error('service_role', 'update public.confirmation_sessions set publish_consent = true', '42501');
  perform pg_temp.expect_error('service_role', 'update public.confirmation_answers set answer = answer', '42501');
  perform pg_temp.expect_error('service_role', 'update public.confirmation_dietary_answers set answer = answer', '42501');
  perform pg_temp.expect_error('service_role', 'delete from public.menus', '42501');
  perform pg_temp.expect_error('service_role', 'delete from public.confirmation_answers', '42501');
  perform pg_temp.expect_error('service_role', 'update public.allergens set name_en = name_en', '42501');
  perform pg_temp.expect_error('service_role', $q$insert into public.allergens (code, name, name_en, category, display_order) values ('x', 'x', 'X', 'required', 1)$q$, '42501');

  -- 所有者権限（管理者接続）でも不変性トリガーが更新を拒否する
  perform pg_temp.expect_error('postgres',
    format('update public.menus set user_publish_consent = true where id = %L', v_menu_a), '55000', 'snapshot_is_immutable');
  perform pg_temp.expect_error('postgres',
    format('update public.dishes set name = %L where menu_id = %L', 'changed', v_menu_a), '55000', 'snapshot_is_immutable');
  perform pg_temp.expect_error('postgres',
    format('update public.confirmation_sessions set publish_consent = true where menu_id = %L', v_menu_a),
    '55000', 'snapshot_is_immutable');
  perform pg_temp.expect_error('postgres',
    format('update public.confirmation_answers set answer = %L where session_id = %L', 'unknown', pg_temp.get('session_1')),
    '55000', 'snapshot_is_immutable');
  perform pg_temp.expect_error('postgres',
    'update public.confirmation_dietary_answers set answer = ''unknown''', '55000', 'snapshot_is_immutable');
end;
$$;

-- ---------------------------------------------------------------------------
\echo '[8/8] public views (guest/non-consent stay private) and storage bucket'
-- ---------------------------------------------------------------------------

do $$
declare
  v_menu_g uuid := pg_temp.get('menu_g')::uuid;
  v_result jsonb;
  v_test_menus uuid[] := array[pg_temp.get('menu_a')::uuid, pg_temp.get('menu_b')::uuid,
                               pg_temp.get('menu_g')::uuid, pg_temp.get('menu_l')::uuid];
begin
  -- ゲストの確認：店員同意ありでも保存はされるが公開されない
  v_result := pg_temp.exec_as('service_role', pg_temp.confirm_sql(
    v_menu_g, pg_temp.h('token-g'), gen_random_uuid(),
    pg_temp.aa(pg_temp.dish_ids(v_menu_g, 1, 2), array[1]), pg_temp.da(pg_temp.dish_ids(v_menu_g, 1, 2), array[1]), true));
  perform pg_temp.assert(
    (select publish_consent and restaurant_id is null
       from public.confirmation_sessions where id = (v_result ->> 'session_id')::uuid),
    'guest confirmation saved with staff consent and no restaurant');

  -- service_role から公開ビューを読める。P0の保存は利用者同意falseのため、検証メニューは公開されない
  v_result := pg_temp.exec_as('service_role', format($q$
    select jsonb_build_array(
      (select count(*) from public.published_menus where menu_id = any(%1$L::uuid[])),
      (select count(*) from public.published_confirmation_answers where menu_id = any(%1$L::uuid[])),
      (select count(*) from public.published_dietary_answers where menu_id = any(%1$L::uuid[])))$q$,
    v_test_menus));
  perform pg_temp.assert(v_result = '[0, 0, 0]'::jsonb,
    format('no test menu (incl. staff consent true) is published: %s', v_result));

  -- 同意falseのメニューにつく回答は公開回答ビューにも一切出ない
  perform pg_temp.assert(
    not exists (select 1 from public.published_confirmation_answers p
                  join public.menus m on m.id = p.menu_id where not m.user_publish_consent)
    and not exists (select 1 from public.published_dietary_answers p
                  join public.menus m on m.id = p.menu_id where not m.user_publish_consent)
    and not exists (select 1 from public.published_menus p
                  join public.menus m on m.id = p.menu_id where not m.user_publish_consent),
    'no row from a non-consenting menu appears in any public view');

  -- Storage：非公開・2 MiB・JPEG/PNGのみ、menu-images を対象にしたポリシーなし
  perform pg_temp.assert(
    (select not b.public and b.file_size_limit = 2097152
            and (select array_agg(m order by m) from unnest(b.allowed_mime_types) as m) = array['image/jpeg', 'image/png']
       from storage.buckets b where b.id = 'menu-images'),
    'menu-images bucket is private, 2 MiB, jpeg/png only');
  perform pg_temp.assert(
    not exists (select 1 from pg_policies p
                 where p.schemaname = 'storage'
                   and (coalesce(p.qual, '') like '%menu-images%' or coalesce(p.with_check, '') like '%menu-images%')),
    'no storage policy references menu-images');
end;
$$;

\if :{?inject_failure}
\echo 'inject_failure is set: forcing a failure to confirm detection'
do $$ begin perform pg_temp.assert(false, 'injected failure'); end; $$;
\endif

\echo 'verify.sql: all checks passed (rolling back)'
rollback;
