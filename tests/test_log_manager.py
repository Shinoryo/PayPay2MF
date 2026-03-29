"""log_manager モジュールのテスト。"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING

from src.constants import AppConstants
from src.log_manager import write_error_csv, write_parse_error_csv
from src.models import AppConfig, LogSettings, ParseFailure

_DUMMY_CHROME_USER_DATA_DIR = "C:\\dummy"
_DEFAULT_CHROME_PROFILE = "Default"
_DEFAULT_MF_ACCOUNT = "PayPay残高"
_INPUT_CSV_FILENAME = "dummy.csv"
_ERROR_MESSAGE_SELECTOR_TIMEOUT = "selector timeout"
_ERROR_MESSAGE_VALIDATION_FAILED = "validation failed"
_ERROR_CSV_FIELDNAMES = ["failure_index", "error_message"]
_PARSE_ERROR_CSV_FIELDNAMES = ["row_index", "error_type", "error_message"]
_PARSE_ERROR_TYPE_MISSING_COLUMN = "missing_column"
_TRADE_DATE_MISSING_MESSAGE = "取引日 がありません"

if TYPE_CHECKING:
    from pathlib import Path


def _make_config(tmp_path: Path) -> AppConfig:
    """log_manager テスト用の AppConfig を生成する。"""
    csv_file = tmp_path / _INPUT_CSV_FILENAME
    csv_file.write_text(
        AppConstants.EMPTY_STRING,
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )
    return AppConfig(
        chrome_user_data_dir=_DUMMY_CHROME_USER_DATA_DIR,
        chrome_profile=_DEFAULT_CHROME_PROFILE,
        dry_run=False,
        input_csv=csv_file,
        mf_account=_DEFAULT_MF_ACCOUNT,
        log_settings=LogSettings(logs_dir=tmp_path),
    )


def test_write_error_csv_uses_minimum_columns(tmp_path: Path) -> None:
    """登録失敗 CSV が最小列のみを書き出すことを確認する。"""
    out_path = write_error_csv(
        [_ERROR_MESSAGE_SELECTOR_TIMEOUT, _ERROR_MESSAGE_VALIDATION_FAILED],
        _make_config(tmp_path),
    )

    with out_path.open(encoding=AppConstants.ENCODING_UTF8_SIG, newline=AppConstants.EMPTY_STRING) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert reader.fieldnames == _ERROR_CSV_FIELDNAMES
    assert rows == [
        {
            "failure_index": "1",
            "error_message": _ERROR_MESSAGE_SELECTOR_TIMEOUT,
        },
        {
            "failure_index": "2",
            "error_message": _ERROR_MESSAGE_VALIDATION_FAILED,
        },
    ]


def test_write_parse_error_csv_uses_minimum_columns(tmp_path: Path) -> None:
    """解析失敗 CSV が最小列のみを書き出すことを確認する。"""
    failures = [
        ParseFailure(
            row_index=3,
            transaction_id="TX001",
            merchant="テスト商店",
            error_type=_PARSE_ERROR_TYPE_MISSING_COLUMN,
            error_message=_TRADE_DATE_MISSING_MESSAGE,
            raw_row={"取引先": "テスト商店"},
        ),
    ]

    out_path = write_parse_error_csv(failures, _make_config(tmp_path))

    with out_path.open(encoding=AppConstants.ENCODING_UTF8_SIG, newline=AppConstants.EMPTY_STRING) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert reader.fieldnames == _PARSE_ERROR_CSV_FIELDNAMES
    assert rows == [
        {
            "row_index": "3",
            "error_type": _PARSE_ERROR_TYPE_MISSING_COLUMN,
            "error_message": _TRADE_DATE_MISSING_MESSAGE,
        },
    ]
