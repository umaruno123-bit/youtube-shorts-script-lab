"""YouTube側のレート制限(HTTP 429)対策の簡易ユーティリティ。"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


def with_backoff(func: Callable[[], T], retries: int = 4, base_delay: float = 15.0) -> T:
    """429 (Too Many Requests) を検知したら指数バックオフしてリトライする。
    それ以外の例外は即座に再送出する。"""
    for attempt in range(retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - 429以外は呼び出し元に伝播させる
            if "429" in str(exc) and attempt < retries:
                time.sleep(base_delay * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")  # pragma: no cover
