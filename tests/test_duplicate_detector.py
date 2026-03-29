"""duplicate_detector モジュールのテスト。

対応テストケース:
    TC-04-01: 取引番号による重複検知
    TC-04-02: 取引番号欠損時のフォールバック重複検知
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from src.constants import AppConstants
from src.duplicate_detector import (
    DuplicateHistoryError,
    LocalDuplicateDetector,
    create_detector,
)

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
    detector1.flush()

    # 新しいインスタンスで読み込み → 重複として検知
    detector2 = LocalDuplicateDetector(config)
    assert detector2.is_duplicate(tx) is True


def test_local_mark_processed_buffers_writes_until_flush(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """mark_processed はメモリ更新だけを行い、flush 時に一度だけ保存する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)
    save_mock = Mock(wraps=detector._save)
    monkeypatch.setattr(detector, "_save", save_mock)

    detector.mark_processed(transaction_factory(transaction_id="TX001"))
    detector.mark_processed(transaction_factory(transaction_id="TX002"))

    assert save_mock.call_count == 0
    assert (tmp_path / AppConstants.PROCESSED_FILENAME).exists() is False

    detector.flush()

    assert save_mock.call_count == 1
    stored = json.loads(
        (tmp_path / AppConstants.PROCESSED_FILENAME).read_text(
            encoding=AppConstants.DEFAULT_TEXT_ENCODING,
        )
    )
    assert stored["transaction_ids"] == ["TX001", "TX002"]


def test_local_corrupted_history_is_backed_up_and_raises_explicit_error(
    tmp_path: Path,
    app_config_factory,
) -> None:
    """破損した processed.json は退避され、明示エラーに変換されることを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    processed_file = tmp_path / AppConstants.PROCESSED_FILENAME
    corrupted_payload = "{broken json}"
    processed_file.write_text(
        corrupted_payload,
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )

    with pytest.raises(DuplicateHistoryError, match=r"processed\.json"):
        LocalDuplicateDetector(config)

    backup_files = list(tmp_path.glob("processed.corrupted_*.json"))
    assert len(backup_files) == 1
    assert processed_file.exists() is False
    assert (
        backup_files[0].read_text(encoding=AppConstants.DEFAULT_TEXT_ENCODING)
        == corrupted_payload
    )


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
    detector1.flush()

    assert detector1.is_duplicate(tx) is False

    detector2 = LocalDuplicateDetector(config)
    assert detector2.is_duplicate(tx) is False
    assert (tmp_path / AppConstants.PROCESSED_FILENAME).exists() is False


def test_local_save_writes_valid_json_without_leaving_temp_file(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """保存後に processed.json が有効な JSON であり、一時ファイルが残らないことを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)

    detector.mark_processed(transaction_factory(transaction_id="TX_JSON"))
    detector.flush()

    processed_file = tmp_path / AppConstants.PROCESSED_FILENAME
    stored = json.loads(
        processed_file.read_text(encoding=AppConstants.DEFAULT_TEXT_ENCODING)
    )
    assert stored["transaction_ids"] == ["TX_JSON"]
    assert list(tmp_path.glob("processed.json.tmp")) == []


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
