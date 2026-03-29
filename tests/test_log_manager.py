"""log_manager モジュールのテスト。"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING

from src.log_manager import write_error_csv, write_parse_error_csv
from src.models import AppConfig, LogSettings, ParseFailure

if TYPE_CHECKING:
    from pathlib import Path


def _make_config(tmp_path: Path) -> AppConfig:
    """log_manager テスト用の AppConfig を生成する。"""
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


def test_write_error_csv_uses_minimum_columns(tmp_path: Path) -> None:
    """登録失敗 CSV が最小列のみを書き出すことを確認する。"""
    out_path = write_error_csv(["selector timeout", "validation failed"], _make_config(tmp_path))

    with out_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert reader.fieldnames == ["failure_index", "error_message"]
    assert rows == [
        {"failure_index": "1", "error_message": "selector timeout"},
        {"failure_index": "2", "error_message": "validation failed"},
    ]


def test_write_parse_error_csv_uses_minimum_columns(tmp_path: Path) -> None:
    """解析失敗 CSV が最小列のみを書き出すことを確認する。"""
    failures = [
        ParseFailure(
            row_index=3,
            transaction_id="TX001",
            merchant="テスト商店",
            error_type="missing_column",
            error_message="取引日 がありません",
            raw_row={"取引先": "テスト商店"},
        ),
    ]

    out_path = write_parse_error_csv(failures, _make_config(tmp_path))

    with out_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert reader.fieldnames == ["row_index", "error_type", "error_message"]
    assert rows == [
        {
            "row_index": "3",
            "error_type": "missing_column",
            "error_message": "取引日 がありません",
        },
    ]
