"""log_manager モジュールのテスト。

対応テストケース:
    TC-01-08: logs_dir 指定時のログ出力先
    TC-09-01: 解析失敗 CSV の最小列
    TC-09-03: 登録失敗 CSV の最小列
"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING

from src.constants import AppConstants
from src.log_manager import setup_logger, write_error_csv, write_parse_error_csv

_ERROR_MESSAGE_SELECTOR_TIMEOUT = "selector timeout"
_ERROR_MESSAGE_VALIDATION_FAILED = "validation failed"
_ERROR_CSV_FIELDNAMES = ["failure_index", "error_message"]
_PARSE_ERROR_CSV_FIELDNAMES = ["row_index", "error_type", "error_message"]
_PARSE_ERROR_TYPE_MISSING_COLUMN = "missing_column"
_TRADE_DATE_MISSING_MESSAGE = "取引日 がありません"
_LOG_MESSAGE = "logger writes to configured logs dir"

if TYPE_CHECKING:
    from pathlib import Path


def test_setup_logger_writes_log_file_to_configured_logs_dir(
    tmp_path: Path,
    app_config_factory,
) -> None:
    """TC-01-08: setup_logger が logs_dir 配下へログファイルを書き出すことを確認する。"""
    logs_dir = tmp_path / "custom-logs"
    config = app_config_factory(tmp_path, logs_dir=logs_dir, input_csv_name="dummy.csv")

    logger = setup_logger(config)
    logger.info(_LOG_MESSAGE)

    handlers = list(logger.handlers)
    for handler in handlers:
        handler.flush()
        handler.close()
    logger.handlers.clear()

    log_files = list(logs_dir.glob("app_*.log"))
    assert len(log_files) == 1
    assert _LOG_MESSAGE in log_files[0].read_text(
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )


def test_write_error_csv_uses_minimum_columns(
    tmp_path: Path,
    app_config_factory,
) -> None:
    """TC-09-03: 登録失敗 CSV が最小列のみを書き出すことを確認する。"""
    out_path = write_error_csv(
        [_ERROR_MESSAGE_SELECTOR_TIMEOUT, _ERROR_MESSAGE_VALIDATION_FAILED],
        app_config_factory(tmp_path, input_csv_name="dummy.csv"),
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


def test_write_parse_error_csv_uses_minimum_columns(
    tmp_path: Path,
    app_config_factory,
    parse_failure_factory,
) -> None:
    """TC-09-01: 解析失敗 CSV が最小列のみを書き出すことを確認する。"""
    failures = [
        parse_failure_factory(
            transaction_id="TX001",
            merchant="テスト商店",
            error_type=_PARSE_ERROR_TYPE_MISSING_COLUMN,
            error_message=_TRADE_DATE_MISSING_MESSAGE,
            raw_row={"取引先": "テスト商店"},
        ),
    ]

    out_path = write_parse_error_csv(
        failures,
        app_config_factory(tmp_path, input_csv_name="dummy.csv"),
    )

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
