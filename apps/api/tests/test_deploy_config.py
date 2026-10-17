"""Vercelの設定（vercel.json・.vercelignore）の確認（05）。実際のデプロイは行わない。

Vercelは `app/main.py` の `app` を自動で検出し、プロジェクト内のファイルを既定ですべて関数に含める
（2026-10-17に公式ドキュメントで確認）。ここでは、実行時に読むファイルを除外していないこと、
秘密値・開発用のファイルをアップロード・同梱しないこと、実行時間の上限が処理の待ち時間より長いことを確かめる。
"""

import fnmatch
import json
from pathlib import Path

from app.main import app
from app.services import menu_analysis, places
from app.services.images import MAX_IMAGE_BYTES
from app.services.supabase_client import POSTGREST_TIMEOUT_SECONDS, STORAGE_TIMEOUT_SECONDS

API_DIR = Path(__file__).resolve().parent.parent
VERCEL_BODY_LIMIT = 4.5 * 1000 * 1000  # 4.5 MB


def vercel_config() -> dict:
    return json.loads((API_DIR / "vercel.json").read_text(encoding="utf-8"))


def exclude_patterns() -> list[str]:
    pattern = vercel_config()["functions"]["app/main.py"]["excludeFiles"]
    return pattern.strip("{}").split(",")


def ignored_patterns() -> list[str]:
    lines = (API_DIR / ".vercelignore").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def is_ignored(path: str) -> bool:
    ignored = False
    for pattern in ignored_patterns():
        negate = pattern.startswith("!")
        pattern = pattern.lstrip("!")
        target = pattern.rstrip("/")
        if fnmatch.fnmatch(path, target) or path.startswith(target + "/") or fnmatch.fnmatch(Path(path).name, target):
            ignored = not negate
    return ignored


def is_excluded(path: str) -> bool:
    for pattern in exclude_patterns():
        prefix = pattern.removesuffix("/**")
        if fnmatch.fnmatch(path, pattern) or (pattern.endswith("/**") and path.startswith(prefix + "/")):
            return True
        if pattern.startswith("**/") and f"/{pattern[3:].removesuffix('/**')}/" in f"/{path}":
            return True
    return False


def test_entrypoint_is_app_main_app():
    assert (API_DIR / "app" / "main.py").is_file()
    assert app.title == "Meelyze+ API"
    assert (API_DIR / "requirements.txt").is_file()
    assert (API_DIR / ".python-version").read_text().strip() == "3.12"


def test_runtime_files_are_bundled():
    for path in ("prompts/menu_analysis.md", "contracts/menu_analysis.schema.json", "app/main.py", "requirements.txt"):
        assert (API_DIR / path).is_file()
        assert not is_ignored(path), path
        assert not is_excluded(path), path
    # 実行時は __file__ からのパスで読む（作業ディレクトリに依存しない）
    assert menu_analysis.PROMPT_PATH == API_DIR / "prompts" / "menu_analysis.md"
    assert menu_analysis.SCHEMA_PATH == API_DIR / "contracts" / "menu_analysis.schema.json"


def test_secrets_and_dev_files_are_not_uploaded():
    for path in (".env", ".env.local", ".venv/lib/x.py", "tests/test_x.py", "task/03.md", "docs/algorithms.md", "scripts/x.py"):
        assert is_ignored(path), path
    assert not is_ignored(".env.example")
    for path in ("tests/conftest.py", "scripts/compare_openapi.py", "app/__pycache__/main.cpython-312.pyc"):
        assert is_excluded(path), path


def test_duration_covers_ai_wait_and_post_processing():
    max_duration = vercel_config()["functions"]["app/main.py"]["maxDuration"]
    assert max_duration <= 300  # Hobby・Proの既定の上限
    # 解析の主な待ち：レート制限2回・Google・AI 45秒・Storage保存・RPC
    critical = 2 * 2.0 + places.TIMEOUT_SECONDS + menu_analysis.AI_TIMEOUT_SECONDS
    critical += STORAGE_TIMEOUT_SECONDS + POSTGREST_TIMEOUT_SECONDS
    assert critical <= max_duration


def test_request_body_limit_fits_vercel():
    from app.routers.menus import MAX_REQUEST_BYTES

    assert MAX_IMAGE_BYTES == 2 * 1024 * 1024
    assert MAX_REQUEST_BYTES < VERCEL_BODY_LIMIT
