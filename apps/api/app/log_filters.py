"""ログに機密情報を残さないための設定。

Uvicornのアクセスログは既定でクエリ文字列（周辺検索の座標など）とクライアントIPを含むため、
パスだけに置き換える。アプリのログは各所でSQLSTATE・例外の型名・ルートだけを記録する。
"""

import logging

ACCESS_LOGGER = "uvicorn.access"


class AccessLogSanitizer(logging.Filter):
    """uvicorn.access の args `(client_addr, method, full_path, http_version, status)` を書き換える。"""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5:
            _client, method, full_path, http_version, status = args
            path = str(full_path).split("?", 1)[0]
            record.args = ("-", method, path, http_version, status)
        return True


def install_log_filters() -> None:
    logger = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(f, AccessLogSanitizer) for f in logger.filters):
        logger.addFilter(AccessLogSanitizer())
    # httpx は INFO でリクエストURL（APIキー・座標を含みうる）を出すため抑止する
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
