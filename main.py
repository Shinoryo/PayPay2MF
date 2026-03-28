"""PayPay→MoneyForward 自動登録ツールのエントリーポイント。

config.yml を読み込んで CSV パースから MF 登録までのメインフローを実行する。
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.chrome_check import is_chrome_running
from src.config_loader import load_config
from src.csv_parser import parse_csv
from src.duplicate_detector import create_detector
from src.filter import apply_exclude, apply_mapping
from src.log_manager import setup_logger, write_error_csv, write_parse_error_csv
from src.mf_registrar import MFRegistrar


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
        "logs_dir 配下のログ、CSV、PNG は機微情報を含む可能性があります。ローカル保管とし、共有やクラウド同期を避けてください。",
    )

    if config.dry_run:
        logger.info("DRY RUN: ブラウザを起動しません。CSV診断のみ実行します。")

    logger.info("config.yml を読み込みました")

    if not config.dry_run:
        if is_chrome_running():
            logger.error(
                "Chrome が起動中です。Chrome を終了してから再実行してください。",
            )
            sys.exit(1)
        logger.info("Chrome 稼働チェック: 停止済み")

    try:
        transactions, parse_failures = parse_csv(config.input_csv, config)
    except Exception as e:
        logger.error("CSV 読み込みに失敗しました: %s", e)
        sys.exit(1)

    if parse_failures:
        parse_error_csv_path = write_parse_error_csv(parse_failures, config)
        logger.warning("CSV 解析失敗: %d件", len(parse_failures))
        logger.warning("解析エラーCSVを出力しました: %s", parse_error_csv_path.name)
        logger.warning(
            "解析エラーCSVは機微情報を含む可能性があります。共有しないでください。",
        )

    logger.info(
        "CSV 読み込み完了: 正常 %d件 / 解析失敗 %d件",
        len(transactions),
        len(parse_failures),
    )

    passed, excluded = apply_exclude(transactions, config.exclude_prefixes)
    logger.info("除外: %d件", len(excluded))

    mapped = apply_mapping(passed, config.mapping_rules)

    detector = create_detector(config)
    to_process: list = []
    skip_count = 0
    for tx in mapped:
        if detector.is_duplicate(tx):
            skip_count += 1
        else:
            to_process.append(tx)

    logger.info("重複スキップ: %d件", skip_count)
    logger.info("処理対象: %d件", len(to_process))

    if config.dry_run:
        logger.info("ドライラン完了: 登録対象 %d件", len(to_process))
        logger.info("アプリケーションを終了します")
        return

    if not to_process:
        logger.info("登録対象がないためブラウザを起動しません。")
        logger.info("アプリケーションを終了します")
        return

    failed_records: list[str] = []
    success_count = 0

    try:
        with MFRegistrar(config, logger) as registrar:
            for index, tx in enumerate(to_process, start=1):
                try:
                    registrar.register(tx)
                    detector.mark_processed(tx)
                    success_count += 1
                except Exception as e:
                    failed_records.append(str(e))
                    logger.error(
                        "登録失敗 (%d/%d): %s",
                        index,
                        len(to_process),
                        e,
                    )
    except Exception as e:
        logger.error("Chrome の起動またはMFへの遷移に失敗しました: %s", e)
        sys.exit(1)

    logger.info(
        "実行完了: 成功 %d件 / 除外 %d件 / 重複スキップ %d件 / 失敗 %d件",
        success_count,
        len(excluded),
        skip_count,
        len(failed_records),
    )

    if failed_records:
        error_csv_path = write_error_csv(failed_records, config)
        logger.warning("登録失敗CSVを出力しました: %s", error_csv_path.name)
        logger.warning(
            "登録失敗CSVは機微情報を含む可能性があります。共有しないでください。",
        )

    logger.info("アプリケーションを終了します")


if __name__ == "__main__":
    main()
