"""PayPay→MoneyForward 自動登録ツールのエントリーポイント。

config.yml を読み込んで CSV パースから MF 登録までのメインフローを実行する。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.chrome_check import is_chrome_running
from src.config_loader import load_config
from src.csv_parser import parse_csv
from src.duplicate_detector import create_detector
from src.filter import apply_exclude, apply_mapping
from src.log_manager import setup_logger, write_error_csv, write_parse_error_csv
from src.mf_registrar import MFRegistrar

if TYPE_CHECKING:
    import logging

    from src.duplicate_detector import DuplicateDetector
    from src.models import AppConfig, ParseFailure, Transaction


@dataclass(slots=True)
class PreparedTransactions:
    detector: DuplicateDetector
    to_process: list[Transaction]
    excluded_count: int
    skip_count: int


@dataclass(slots=True)
class RegistrationResult:
    success_count: int
    failed_records: list[str]


def ensure_chrome_stopped(config: AppConfig, logger: logging.Logger) -> None:
    if config.dry_run:
        return

    if is_chrome_running():
        logger.error(
            "Chrome が起動中です。Chrome を終了してから再実行してください。",
        )
        sys.exit(1)

    logger.info("Chrome 稼働チェック: 停止済み")


def _log_parse_failures(
    parse_failures: list[ParseFailure],
    config: AppConfig,
    logger: logging.Logger,
) -> None:
    if not parse_failures:
        return

    parse_error_csv_path = write_parse_error_csv(parse_failures, config)
    logger.warning("CSV 解析失敗: %d件", len(parse_failures))
    logger.warning("解析エラーCSVを出力しました: %s", parse_error_csv_path.name)
    logger.warning(
        "解析エラーCSVは機微情報を含む可能性があります。共有しないでください。",
    )


def build_transactions(
    config: AppConfig,
    logger: logging.Logger,
) -> PreparedTransactions:
    try:
        transactions, parse_failures = parse_csv(config.input_csv, config)
    except Exception:
        logger.exception("CSV 読み込みに失敗しました")
        sys.exit(1)

    _log_parse_failures(parse_failures, config, logger)

    logger.info(
        "CSV 読み込み完了: 正常 %d件 / 解析失敗 %d件",
        len(transactions),
        len(parse_failures),
    )

    passed, excluded = apply_exclude(transactions, config.exclude_prefixes)
    logger.info("除外: %d件", len(excluded))

    mapped = apply_mapping(passed, config.mapping_rules)

    detector = create_detector(config)
    to_process: list[Transaction] = []
    skip_count = 0

    for tx in mapped:
        if detector.is_duplicate(tx):
            skip_count += 1
            continue
        to_process.append(tx)

    logger.info("重複スキップ: %d件", skip_count)
    logger.info("処理対象: %d件", len(to_process))

    return PreparedTransactions(
        detector=detector,
        to_process=to_process,
        excluded_count=len(excluded),
        skip_count=skip_count,
    )


def run_dry_run(logger: logging.Logger, to_process_count: int) -> None:
    logger.info("ドライラン完了: 登録対象 %d件", to_process_count)
    logger.info("アプリケーションを終了します")


def _register_transaction(
    registrar: MFRegistrar,
    detector: DuplicateDetector,
    logger: logging.Logger,
    tx: Transaction,
    *,
    progress: tuple[int, int],
) -> str | None:
    index, total_count = progress

    try:
        registrar.register(tx)
        detector.mark_processed(tx)
    except Exception as exc:
        logger.exception(
            "登録失敗 (%d/%d): %s",
            index,
            total_count,
            exc,
        )
        return str(exc)

    return None


def run_registration(
    config: AppConfig,
    logger: logging.Logger,
    detector: DuplicateDetector,
    to_process: list[Transaction],
) -> RegistrationResult:
    failed_records: list[str] = []
    success_count = 0

    try:
        with MFRegistrar(config, logger) as registrar:
            for index, tx in enumerate(to_process, start=1):
                error_message = _register_transaction(
                    registrar,
                    detector,
                    logger,
                    tx,
                    progress=(index, len(to_process)),
                )
                if error_message is None:
                    success_count += 1
                    continue

                failed_records.append(error_message)
    except Exception:
        logger.exception("Chrome の起動またはMFへの遷移に失敗しました")
        sys.exit(1)

    return RegistrationResult(
        success_count=success_count,
        failed_records=failed_records,
    )


def log_summary(
    logger: logging.Logger,
    config: AppConfig,
    prepared: PreparedTransactions,
    registration_result: RegistrationResult,
) -> None:
    logger.info(
        "実行完了: 成功 %d件 / 除外 %d件 / 重複スキップ %d件 / 失敗 %d件",
        registration_result.success_count,
        prepared.excluded_count,
        prepared.skip_count,
        len(registration_result.failed_records),
    )

    if registration_result.failed_records:
        error_csv_path = write_error_csv(registration_result.failed_records, config)
        logger.warning("登録失敗CSVを出力しました: %s", error_csv_path.name)
        logger.warning(
            "登録失敗CSVは機微情報を含む可能性があります。共有しないでください。",
        )


def main() -> None:
    """アプリケーションのメイン処理を実行する。

    処理フロー:
        1. 設定ファイル読み込み
        2. Chrome 起動確認（dry_run 以外）
        3. CSV パース
        4. 除外フィルタ適用
        5. カテゴリマッピング適用
        6. 重複チェック
        7. MF 登録（dry_run の場合は診断ログを出力）
        8. サマリーログ出力・エラー CSV 書き出し
    """
    config_path = Path(__file__).parent / "config.yml"

    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] 設定ファイルの読み込みに失敗しました:\n{e}")
        sys.exit(1)

    logger = setup_logger(config)
    logger.warning(
        "logs_dir 配下のログ、CSV、PNG は機微情報を含む可能性があります。"
        "ローカル保管とし、共有やクラウド同期を避けてください。",
    )

    if config.dry_run:
        logger.info("DRY RUN: ブラウザを起動しません。CSV診断のみ実行します。")

    logger.info("config.yml を読み込みました")

    ensure_chrome_stopped(config, logger)
    prepared = build_transactions(config, logger)

    if config.dry_run:
        run_dry_run(logger, len(prepared.to_process))
        return

    if not prepared.to_process:
        logger.info("登録対象がないためブラウザを起動しません。")
        logger.info("アプリケーションを終了します")
        return

    registration_result = run_registration(
        config,
        logger,
        prepared.detector,
        prepared.to_process,
    )

    log_summary(
        logger,
        config,
        prepared,
        registration_result,
    )

    logger.info("アプリケーションを終了します")


if __name__ == "__main__":
    main()
