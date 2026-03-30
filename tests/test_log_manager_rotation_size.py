"""log_manager のサイズベースローテーション検証テスト。"""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING

from paypay2mf import log_manager

if TYPE_CHECKING:
    from pathlib import Path


def test_rotate_logs_by_size_removes_oldest_until_total_within_limit(
    tmp_path: Path, monkeypatch, app_config_factory
) -> None:
    """公開 API 経由で古いログが削除され、合計が閾値以下になることを確認する。

    既存ログを超過状態で作成してから setup_logger を呼び、
    ローテーションが最古ファイルから順に行われることを確認する。
    """

    class _FrozenDateTime:
        @classmethod
        def now(cls) -> datetime:
            return datetime(2025, 1, 1, 12, 0, 0)  # noqa: DTZ001

    logs_dir = tmp_path / "custom-logs"
    logs_dir.mkdir()

    size_mb = 1024 * 1024
    sizes = [1, 2, 3, 4]
    for i, size in enumerate(sizes):
        p = logs_dir / f"app_{i:02}.log"
        p.write_bytes(b"x" * (size * size_mb))
        os.utime(p, (i, i))

    monkeypatch.setattr(log_manager, "datetime", _FrozenDateTime)

    config = app_config_factory(tmp_path, logs_dir=logs_dir)
    config.log_settings.max_total_log_size_mb = 6

    logger = log_manager.setup_logger(config)
    for handler in logger.handlers:
        handler.flush()

    remaining = sorted(logs_dir.glob("app_*.log"), key=os.path.getmtime)
    assert [p.name for p in remaining] == ["app_03.log", "app_20250101_120000.log"]
    assert sum(p.stat().st_size for p in remaining) <= 6 * size_mb
