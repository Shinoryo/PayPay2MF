"""ロガーセットアップ・エラー CSV 書き込み・ログローテーション。

アプリケーション実行ログの生成・ローテーション、
エラー内容の CSV 出力機能を提供する。
"""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import AppConfig, ParseFailure, Transaction

# ロガー設定
_LOGGER_NAME = "paypay2mf"
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_FILE_LOG_LEVEL = logging.DEBUG
_CONSOLE_LOG_LEVEL = logging.INFO

# ファイル名・エンコーディング
_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
_LOG_FILE_PREFIX = "app_"
_LOG_FILE_SUFFIX = ".log"
_LOG_GLOB_PATTERN = f"{_LOG_FILE_PREFIX}*{_LOG_FILE_SUFFIX}"
_LOG_FILE_ENCODING = "utf-8"
_ERROR_CSV_PREFIX = "error_"
_ERROR_CSV_SUFFIX = ".csv"
_ERROR_CSV_ENCODING = "utf-8-sig"

# デフォルトディレクトリ
_DEFAULT_LOGS_DIR_NAME = "logs"

# サイズ計算
_BYTES_PER_MB = 1024 * 1024

# エラー CSV
_CSV_DATE_FORMAT = "%Y/%m/%d %H:%M:%S"
_ERROR_CSV_FIELDNAMES = (
    "date",
    "amount",
    "direction",
    "memo",
    "merchant",
    "transaction_id",
    "category",
)
_PARSE_ERROR_CSV_PREFIX = "parse_error_"
_PARSE_ERROR_CSV_FIELDNAMES = (
    "row_index",
    "transaction_id",
    "merchant",
    "error_type",
    "error_message",
    "raw_row",
)


def setup_logger(config: AppConfig) -> logging.Logger:
    """アプリケーションロガーを設定して返す。

    ログディレクトリを作成し、ファイルハンドラー（DEBUG）と
    コンソールハンドラー（INFO）を設定する。
    max_log_count または max_total_log_size_mb が設定されている場合は
    古いログを自動削除する。

    Args:
        config: アプリケーション設定。

    Returns:
        設定済みの Logger インスタンス。
    """
    logs_dir = _resolve_logs_dir(config)
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)  # noqa: DTZ005
    log_file = logs_dir / f"{_LOG_FILE_PREFIX}{timestamp}{_LOG_FILE_SUFFIX}"

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fh = logging.FileHandler(log_file, encoding=_LOG_FILE_ENCODING)
    fh.setLevel(_FILE_LOG_LEVEL)
    fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(_CONSOLE_LOG_LEVEL)
    ch.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(ch)

    _rotate_logs(config, logs_dir)

    return logger


def write_error_csv(
    records: list[Transaction], config: AppConfig,
) -> Path:
    """エラーが発生した Transaction を CSV ファイルに書き出す。

    Args:
        records: エラーとなった Transaction のリスト。
        config: アプリケーション設定。

    Returns:
        書き出した CSV ファイルのパス。
    """
    logs_dir = _resolve_logs_dir(config)
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)  # noqa: DTZ005
    out_path = logs_dir / f"{_ERROR_CSV_PREFIX}{timestamp}{_ERROR_CSV_SUFFIX}"

    with out_path.open("w", newline="", encoding=_ERROR_CSV_ENCODING) as f:
        writer = csv.DictWriter(f, fieldnames=_ERROR_CSV_FIELDNAMES)
        writer.writeheader()
        for tx in records:
            writer.writerow(
                {
                    "date": tx.date.strftime(_CSV_DATE_FORMAT),
                    "amount": tx.amount,
                    "direction": tx.direction,
                    "memo": tx.memo,
                    "merchant": tx.merchant,
                    "transaction_id": tx.transaction_id or "",
                    "category": tx.category,
                },
            )

    return out_path


def write_parse_error_csv(
    records: list[ParseFailure], config: AppConfig,
) -> Path:
    """CSV 解析に失敗した行を CSV ファイルに書き出す。"""
    logs_dir = _resolve_logs_dir(config)
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)  # noqa: DTZ005
    out_path = logs_dir / f"{_PARSE_ERROR_CSV_PREFIX}{timestamp}{_ERROR_CSV_SUFFIX}"

    with out_path.open("w", newline="", encoding=_ERROR_CSV_ENCODING) as f:
        writer = csv.DictWriter(f, fieldnames=_PARSE_ERROR_CSV_FIELDNAMES)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "row_index": record.row_index,
                    "transaction_id": record.transaction_id or "",
                    "merchant": record.merchant or "",
                    "error_type": record.error_type,
                    "error_message": record.error_message,
                    "raw_row": json.dumps(record.raw_row, ensure_ascii=False),
                },
            )

    return out_path


def _resolve_logs_dir(config: AppConfig) -> Path:
    """ログディレクトリのパスを解決して返す。

    config.log_settings.logs_dir が設定されていない場合は
    ツールフォルダ直下の ``logs`` ディレクトリを使用する。

    Args:
        config: アプリケーション設定。

    Returns:
        ログディレクトリの Path。
    """
    if config.log_settings.logs_dir:
        return config.log_settings.logs_dir
    return Path(__file__).parent.parent / _DEFAULT_LOGS_DIR_NAME


def _rotate_logs(config: AppConfig, logs_dir: Path) -> None:
    """ログローテーションを実行する。

    max_log_count または max_total_log_size_mb を超えている場合、
    古いログファイルから順に削除する。

    Args:
        config: アプリケーション設定。
        logs_dir: ログディレクトリの Path。
    """
    log_files = sorted(
        logs_dir.glob(_LOG_GLOB_PATTERN), key=os.path.getmtime,
    )

    max_count = config.log_settings.max_log_count
    if max_count is not None:
        while len(log_files) > max_count:
            log_files.pop(0).unlink(missing_ok=True)

    max_size_mb = config.log_settings.max_total_log_size_mb
    if max_size_mb is not None:
        max_bytes = max_size_mb * _BYTES_PER_MB
        while log_files:
            total = sum(
                f.stat().st_size for f in log_files if f.exists()
            )
            if total <= max_bytes:
                break
            log_files.pop(0).unlink(missing_ok=True)
