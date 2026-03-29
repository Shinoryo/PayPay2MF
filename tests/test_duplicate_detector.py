"""duplicate_detector モジュールのテスト。

対応テストケース:
    TC-04-01: 取引番号による重複検知
    TC-04-02: 取引番号欠損時のフォールバック重複検知
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.constants import AppConstants
from src.duplicate_detector import LocalDuplicateDetector, create_detector

if TYPE_CHECKING:
    from pathlib import Path


# TC-04-01: 取引番号による重複検知
def test_local_duplicate_by_id(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """TC-04-01: 同一 transaction_id の取引が重複として検知されることを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)

    tx = transaction_factory(transaction_id="TX001")
    assert detector.is_duplicate(tx) is False

    detector.mark_processed(tx)
    assert detector.is_duplicate(tx) is True


# TC-04-02: 取引番号欠損時のフォールバック（日時+金額+取引先）
def test_local_duplicate_fallback(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """TC-04-02: transaction_id が None の場合に日時・金額・取引先でフォールバック判定がされることを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)

    tx = transaction_factory(transaction_id=None, merchant="テスト商店", amount=500)
    assert detector.is_duplicate(tx) is False

    detector.mark_processed(tx)
    assert detector.is_duplicate(tx) is True


# 重複なし（別取引番号）
def test_local_no_duplicate(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """別の transaction_id を持つ取引が重複として判定されないことを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)

    tx1 = transaction_factory(transaction_id="TX001")
    tx2 = transaction_factory(transaction_id="TX002")

    detector.mark_processed(tx1)
    assert detector.is_duplicate(tx2) is False


# mark_processed が JSON に永続化される
def test_local_persistence(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """mark_processed の結果が JSON ファイルに永続化され、新しいインスタンスでも読み込まれることを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")

    detector1 = LocalDuplicateDetector(config)
    tx = transaction_factory(transaction_id="TX_PERSIST")
    detector1.mark_processed(tx)

    # 新しいインスタンスで読み込み → 重複として検知
    detector2 = LocalDuplicateDetector(config)
    assert detector2.is_duplicate(tx) is True


def test_local_dry_run_does_not_persist(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """dry_run=True の場合は mark_processed を呼んでも状態が保存されないことを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_name="dummy.csv")

    detector1 = LocalDuplicateDetector(config)
    tx = transaction_factory(transaction_id="TX_DRY_RUN")
    detector1.mark_processed(tx)

    assert detector1.is_duplicate(tx) is False

    detector2 = LocalDuplicateDetector(config)
    assert detector2.is_duplicate(tx) is False
    assert (tmp_path / AppConstants.PROCESSED_FILENAME).exists() is False


# フォールバック: tolerance_seconds 内は重複
def test_local_fallback_within_tolerance(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """tolerance_seconds 以内の時刻差を持つ同額取引がフォールバック重複として検知されることを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)

    base = datetime(2025, 1, 1, 12, 0, 0)  # noqa: DTZ001
    tx1 = transaction_factory(transaction_id=None, amount=300, date=base)
    detector.mark_processed(tx1)

    # 30秒後 → tolerance_seconds=60 内なので重複
    tx2 = transaction_factory(
        transaction_id=None,
        amount=300,
        date=base + timedelta(seconds=30),
    )
    assert detector.is_duplicate(tx2) is True


# create_detector が LocalDuplicateDetector を返す
def test_create_detector_local(tmp_path: Path, app_config_factory) -> None:
    """create_detector が backend="local" の場合に LocalDuplicateDetector を返すことを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = create_detector(config)
    assert isinstance(detector, LocalDuplicateDetector)
