"""duplicate_detector モジュールのテスト。

対応テストケース:
    TC-04-01: 取引番号による重複検知
    TC-04-02: 取引番号欠損時のフォールバック重複検知
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.duplicate_detector import LocalDuplicateDetector, create_detector
from src.models import AppConfig, LogSettings, Transaction

if TYPE_CHECKING:
    from pathlib import Path


def _make_config(tmp_path: Path) -> AppConfig:
    """テスト用の AppConfig を生成する。

    Args:
        tmp_path: pytest の tmp_path フィクスチャ。

    Returns:
        logs_dir が tmp_path に設定されたテスト用 AppConfig インスタンス。
    """
    csv_file = tmp_path / "dummy.csv"
    csv_file.write_text("", encoding="utf-8")
    return AppConfig(
        chrome_user_data_dir="C:\\dummy",
        chrome_profile="Default",
        dry_run=False,
        input_csv=csv_file,
        mf_account="PayPay残高",
        log_settings=LogSettings(logs_dir=tmp_path),
    )


def _make_tx(
    transaction_id: str | None = "TX001",
    merchant: str = "テスト商店",
    amount: int = 100,
    date: datetime | None = None,
) -> Transaction:
    """テスト用の Transaction を生成する。

    Args:
        transaction_id: 取引番号。デフォルトは "TX001"。
        merchant: 取引先名。デフォルトは "テスト商店"。
        amount: 金額。デフォルトは 100。
        date: 取引日時。None の場合は 2025-01-01 12:00:00 を使用する。

    Returns:
        テスト用 Transaction インスタンス。
    """
    return Transaction(
        date=date or datetime(2025, 1, 1, 12, 0, 0),  # noqa: DTZ001
        amount=amount,
        direction="out",
        memo="支払い",
        merchant=merchant,
        transaction_id=transaction_id,
    )


# TC-04-01: 取引番号による重複検知
def test_local_duplicate_by_id(tmp_path: Path) -> None:
    """TC-04-01: 同一 transaction_id の取引が重複として検知されることを確認する。"""
    config = _make_config(tmp_path)
    detector = LocalDuplicateDetector(config)

    tx = _make_tx(transaction_id="TX001")
    assert detector.is_duplicate(tx) is False

    detector.mark_processed(tx)
    assert detector.is_duplicate(tx) is True


# TC-04-02: 取引番号欠損時のフォールバック（日時+金額+取引先）
def test_local_duplicate_fallback(tmp_path: Path) -> None:
    """TC-04-02: transaction_id が None の場合に日時・金額・取引先でフォールバック判定がされることを確認する。"""
    config = _make_config(tmp_path)
    detector = LocalDuplicateDetector(config)

    tx = _make_tx(transaction_id=None, merchant="テスト商店", amount=500)
    assert detector.is_duplicate(tx) is False

    detector.mark_processed(tx)
    assert detector.is_duplicate(tx) is True


# 重複なし（別取引番号）
def test_local_no_duplicate(tmp_path: Path) -> None:
    """別の transaction_id を持つ取引が重複として判定されないことを確認する。"""
    config = _make_config(tmp_path)
    detector = LocalDuplicateDetector(config)

    tx1 = _make_tx(transaction_id="TX001")
    tx2 = _make_tx(transaction_id="TX002")

    detector.mark_processed(tx1)
    assert detector.is_duplicate(tx2) is False


# mark_processed が JSON に永続化される
def test_local_persistence(tmp_path: Path) -> None:
    """mark_processed の結果が JSON ファイルに永続化され、新しいインスタンスでも読み込まれることを確認する。"""
    config = _make_config(tmp_path)

    detector1 = LocalDuplicateDetector(config)
    tx = _make_tx(transaction_id="TX_PERSIST")
    detector1.mark_processed(tx)

    # 新しいインスタンスで読み込み → 重複として検知
    detector2 = LocalDuplicateDetector(config)
    assert detector2.is_duplicate(tx) is True


def test_local_dry_run_does_not_persist(tmp_path: Path) -> None:
    """dry_run=True の場合は mark_processed を呼んでも状態が保存されないことを確認する。"""
    config = _make_config(tmp_path)
    config.dry_run = True

    detector1 = LocalDuplicateDetector(config)
    tx = _make_tx(transaction_id="TX_DRY_RUN")
    detector1.mark_processed(tx)

    assert detector1.is_duplicate(tx) is False

    detector2 = LocalDuplicateDetector(config)
    assert detector2.is_duplicate(tx) is False
    assert (tmp_path / "processed.json").exists() is False


# フォールバック: tolerance_seconds 内は重複
def test_local_fallback_within_tolerance(tmp_path: Path) -> None:
    """tolerance_seconds 以内の時刻差を持つ同額取引がフォールバック重複として検知されることを確認する。"""
    config = _make_config(tmp_path)
    detector = LocalDuplicateDetector(config)

    base = datetime(2025, 1, 1, 12, 0, 0)  # noqa: DTZ001
    tx1 = _make_tx(transaction_id=None, amount=300, date=base)
    detector.mark_processed(tx1)

    # 30秒後 → tolerance_seconds=60 内なので重複
    tx2 = _make_tx(
        transaction_id=None,
        amount=300,
        date=base + timedelta(seconds=30),
    )
    assert detector.is_duplicate(tx2) is True


# create_detector が LocalDuplicateDetector を返す
def test_create_detector_local(tmp_path: Path) -> None:
    """create_detector が backend="local" の場合に LocalDuplicateDetector を返すことを確認する。"""
    config = _make_config(tmp_path)
    detector = create_detector(config)
    assert isinstance(detector, LocalDuplicateDetector)
