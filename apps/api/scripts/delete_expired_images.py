"""作成から24時間を過ぎたメニュー画像を、Storage APIで削除する（開発中の手動手順。05）。

  # 対象の件数だけを表示（既定。削除しない）
  .venv/bin/python scripts/delete_expired_images.py
  # 削除する。ローカル以外の接続先では --allow-remote も必要
  .venv/bin/python scripts/delete_expired_images.py --apply [--allow-remote]

- 接続先は `apps/api/.env`（または環境変数）の `SUPABASE_URL`・`SUPABASE_SECRET_KEY`。実行前に表示される接続先を確認する。
- 削除するのは非公開バケット `menu-images` のオブジェクトだけ。メニュー・料理・回答・本人履歴の行と
  `menus.image_path` は残す。`storage.objects` を直接DELETEしない。
- 画像のパス・メニューIDは表示しない（件数だけ）。
- 一般公開前の定期削除（スケジュール実行）と保持期間の判断は00のU4に引き継ぐ。
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

API_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_DIR))

BUCKET = "menu-images"
RETENTION = timedelta(hours=24)
PAGE_SIZE = 1000
REMOVE_BATCH = 100
LOCAL_HOSTS = ("127.0.0.1", "localhost")


def expired_image_paths(
    client, now: datetime, retention: timedelta = RETENTION, path_prefix: str | None = None
) -> list[str]:
    cutoff = (now - retention).isoformat()
    paths: list[str] = []
    offset = 0
    while True:
        query = client.table("menus").select("image_path").lt("created_at", cutoff)
        if path_prefix:
            query = query.like("image_path", f"{path_prefix}%")
        rows = (
            query.order("created_at")
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
        )
        paths.extend(row["image_path"] for row in rows)
        if len(rows) < PAGE_SIZE:
            return paths
        offset += PAGE_SIZE


def existing_objects(client, paths: list[str]) -> list[str]:
    """Storageに残っているものだけ（削除済みは除く）。フォルダごとに一覧を取る。"""
    bucket = client.storage.from_(BUCKET)
    folders: dict[str, set[str]] = {}
    for path in paths:
        folder, _, name = path.rpartition("/")
        folders.setdefault(folder, set()).add(name)
    remaining = []
    for folder, names in folders.items():
        present: set[str] = set()
        offset = 0
        while True:
            items = bucket.list(folder, {"limit": PAGE_SIZE, "offset": offset})
            present.update(item["name"] for item in items)
            if len(items) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        remaining.extend(f"{folder}/{name}" if folder else name for name in sorted(names & present))
    return remaining


def delete_images(client, paths: list[str]) -> int:
    bucket = client.storage.from_(BUCKET)
    deleted = 0
    for start in range(0, len(paths), REMOVE_BATCH):
        deleted += len(bucket.remove(paths[start : start + REMOVE_BATCH]) or [])
    return deleted


def run(client, *, apply: bool, now: datetime | None = None, path_prefix: str | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    expired = expired_image_paths(client, now, path_prefix=path_prefix)
    targets = existing_objects(client, expired)
    result = {"expired_menus": len(expired), "images_remaining": len(targets), "deleted": 0}
    if apply and targets:
        result["deleted"] = delete_images(client, targets)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="削除する（指定しなければ件数の表示だけ）")
    parser.add_argument("--allow-remote", action="store_true", help="ローカル以外のSupabaseで削除を許可する")
    parser.add_argument("--prefix", help="対象を image_path がこの文字列で始まるものに限る（例 menus/）")
    args = parser.parse_args()

    from app.config import Settings
    from app.services.supabase_client import _create

    settings = Settings()
    if not settings.supabase_url or settings.supabase_secret_key is None:
        print("SUPABASE_URL・SUPABASE_SECRET_KEY が未設定です", file=sys.stderr)
        return 2
    host = urlsplit(settings.supabase_url).hostname or ""
    print(f"接続先: {host}")
    if args.apply and host not in LOCAL_HOSTS and not args.allow_remote:
        print("ローカル以外で削除するには --allow-remote を付けてください（対象と件数を確認してから）", file=sys.stderr)
        return 2

    result = run(_create(settings.supabase_url, settings.supabase_secret_key.get_secret_value()), apply=args.apply, path_prefix=args.prefix)
    print(f"24時間を過ぎたメニュー: {result['expired_menus']}件")
    print(f"Storageに残っている画像: {result['images_remaining']}件")
    print(f"削除した画像: {result['deleted']}件" if args.apply else "（--apply を付けていないため削除していない）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
