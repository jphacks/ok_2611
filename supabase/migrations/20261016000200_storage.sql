-- 非公開バケット menu-images。正本は docs/database.md の「Storage」。
-- 既存のバケットの設定が異なる場合は上書きせず例外で停止する。
-- anon／authenticated 向けのポリシーは作らない。画像の削除は Storage API で行い、storage.objects を直接DELETEしない。

do $$
declare
  v_bucket storage.buckets%rowtype;
  v_mime text[];
begin
  select b.*
    into v_bucket
    from storage.buckets b
   where b.id = 'menu-images';

  if not found then
    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values ('menu-images', 'menu-images', false, 2097152, array['image/jpeg', 'image/png']);
  else
    select array_agg(m.value order by m.value)
      into v_mime
      from unnest(v_bucket.allowed_mime_types) as m(value);

    if v_bucket.name is distinct from 'menu-images'
       or v_bucket.public is distinct from false
       or v_bucket.file_size_limit is distinct from 2097152
       or v_mime is distinct from array['image/jpeg', 'image/png'] then
      raise exception 'menu-images bucket exists with unexpected settings (public=%, file_size_limit=%, allowed_mime_types=%)',
        v_bucket.public, v_bucket.file_size_limit, v_bucket.allowed_mime_types;
    end if;
  end if;

  -- このバケットを対象にした既存のポリシーがあれば停止する（クライアントからの操作を許さない）。
  if exists (
       select 1
         from pg_catalog.pg_policies p
        where p.schemaname = 'storage'
          and (coalesce(p.qual, '') like '%menu-images%'
               or coalesce(p.with_check, '') like '%menu-images%')
     ) then
    raise exception 'storage policy referencing menu-images exists; client access must not be granted';
  end if;
end;
$$;
