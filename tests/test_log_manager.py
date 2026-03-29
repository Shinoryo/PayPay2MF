"""log_manager モジュールのテスト。

対応テストケース:
    TC-01-08: logs_dir 指定時のログ出力先
    TC-09-01: 解析失敗 CSV の最小列
    TC-09-03: 登録失敗 CSV の最小列
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from paypay2mf import log_manager
from paypay2mf.constants import AppConstants
from paypay2mf.log_manager import setup_logger, write_error_csv, write_parse_error_csv

_ERROR_MESSAGE_SELECTOR_TIMEOUT = "selector timeout"
_ERROR_MESSAGE_VALIDATION_FAILED = "validation failed"
_ERROR_CSV_FIELDNAMES = ["failure_index", "error_message"]
_PARSE_ERROR_CSV_FIELDNAMES = ["row_index", "error_type", "error_message"]
_PARSE_ERROR_TYPE_MISSING_COLUMN = "missing_column"
_TRADE_DATE_MISSING_MESSAGE = "取引日 がありません"
_LOG_MESSAGE = "logger writes to configured logs dir"

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def cleanup_logger_handlers() -> Iterator[None]:
    """各テスト後に paypay2mf logger の handler を解放する。"""
    yield

    logger = logging.getLogger("paypay2mf")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.flush()
        handler.close()


def test_setup_logger_writes_log_file_to_configured_logs_dir(
    tmp_path: Path,
    app_config_factory,
) -> None:
    """TC-01-08: setup_logger が logs_dir 配下へログファイルを書き出すことを確認する。"""
    logs_dir = tmp_path / "custom-logs"
    config = app_config_factory(tmp_path, logs_dir=logs_dir, input_csv_name="dummy.csv")

    logger = setup_logger(config)
    logger.info(_LOG_MESSAGE)

    for handler in logger.handlers:
        handler.flush()

    log_files = list(logs_dir.glob("app_*.log"))
    assert len(log_files) == 1
    assert _LOG_MESSAGE in log_files[0].read_text(
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )


def test_setup_logger_reinitialization_closes_existing_file_handler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    app_config_factory,
) -> None:
    """setup_logger 再実行時に既存 FileHandler を close する。"""

    class _FrozenDateTime:
        _timestamps = iter(
            [
                datetime(2025, 1, 1, 12, 0, 0),  # noqa: DTZ001
                datetime(2025, 1, 1, 12, 0, 1),  # noqa: DTZ001
            ],
        )

        @classmethod
        def now(cls) -> datetime:
            return next(cls._timestamps)

    logs_dir = tmp_path / "custom-logs"
    config = app_config_factory(tmp_path, logs_dir=logs_dir, input_csv_name="dummy.csv")
    monkeypatch.setattr(log_manager, "datetime", _FrozenDateTime)

    first_logger = setup_logger(config)
    first_logger.info("first")
    first_file_handler = next(
        handler
        for handler in first_logger.handlers
        if isinstance(handler, logging.FileHandler)
    )
    for handler in first_logger.handlers:
        handler.flush()

    first_log_path = logs_dir / "app_20250101_120000.log"
    assert first_log_path.exists()

    second_logger = setup_logger(config)
    second_logger.info("second")
    for handler in second_logger.handlers:
        handler.flush()

    assert first_file_handler not in second_logger.handlers
    assert first_file_handler.stream is None

    first_log_path.unlink()
    assert not first_log_path.exists()
    assert (logs_dir / "app_20250101_120001.log").exists()


def test_setup_logger_keeps_active_log_when_max_count_is_zero(
    tmp_path: Path,
    app_config_factory,
) -> None:
    """max_log_count=0 でも実行中のログファイル削除を試みないことを確認する。"""
    logs_dir = tmp_path / "custom-logs"
    config = app_config_factory(tmp_path, logs_dir=logs_dir, input_csv_name="dummy.csv")
    config.log_settings.max_log_count = 0

    old_log = logs_dir / "app_old.log"
    logs_dir.mkdir(parents=True, exist_ok=True)
    old_log.write_text("old", encoding=AppConstants.DEFAULT_TEXT_ENCODING)

    logger = setup_logger(config)
    logger.info(_LOG_MESSAGE)

    for handler in logger.handlers:
        handler.flush()

    log_files = list(logs_dir.glob("app_*.log"))
    assert len(log_files) == 1
    assert log_files[0].name != old_log.name
    assert old_log.exists() is False


def test_write_error_csv_uses_minimum_columns(
    tmp_path: Path,
    app_config_factory,
) -> None:
    """TC-09-03: 登録失敗 CSV が最小列のみを書き出すことを確認する。"""
    out_path = write_error_csv(
        [_ERROR_MESSAGE_SELECTOR_TIMEOUT, _ERROR_MESSAGE_VALIDATION_FAILED],
        app_config_factory(tmp_path, input_csv_name="dummy.csv"),
    )

    with out_path.open(
        encoding=AppConstants.ENCODING_UTF8_SIG, newline=AppConstants.EMPTY_STRING
    ) as f:
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

    with out_path.open(
        encoding=AppConstants.ENCODING_UTF8_SIG, newline=AppConstants.EMPTY_STRING
    ) as f:
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
