"""公開データの照合。読み取り元は公開ビューだけ（基礎テーブルを読まない）。

`published_menus` は店舗あり・利用者同意true・店員同意trueの確認が1件以上あるメニューの料理を1行ずつ返す。
`public_menu_count` は、Place IDごとの異なる `name_key` の数とする。API 7（⑦）は同じ店舗の
`name_key` ごとに1料理へまとめて返すため、⑥で見た件数と⑦に表示される料理数が一致する。
"""

from collections.abc import Iterable

from supabase import Client

PAGE_SIZE = 1000  # PostgRESTの既定の最大行数に合わせてページングする


def count_public_dishes(client: Client, google_place_ids: Iterable[str]) -> dict[str, int]:
    place_ids = sorted(set(google_place_ids))
    if not place_ids:
        return {}
    name_keys: dict[str, set[str]] = {place_id: set() for place_id in place_ids}
    offset = 0
    while True:
        rows = (
            client.table("published_menus")
            .select("google_place_id,name_key")
            .in_("google_place_id", place_ids)
            .order("menu_id")
            .order("dish_id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
        )
        for row in rows:
            if row["google_place_id"] in name_keys:
                name_keys[row["google_place_id"]].add(row["name_key"])
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return {place_id: len(keys) for place_id, keys in name_keys.items()}
