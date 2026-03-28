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
from src.log_manager import setup_logger, write_error_csv
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

    logger.info("input_csv: %s", config.input_csv)

    try:
        transactions = parse_csv(config.input_csv, config)
    except Exception as e:
        logger.error("CSV 読み込みに失敗しました: %s", e)
        sys.exit(1)

    logger.info("CSV 読み込み完了: %d件", len(transactions))

    passed, excluded = apply_exclude(transactions, config.exclude_prefixes)
    excluded_ids = ", ".join(
        tx.transaction_id or "（不明）" for tx in excluded
    )
    logger.info("除外: %d件 (%s)", len(excluded), excluded_ids)

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
        for tx in to_process:
            amount_str = (
                f"+{tx.amount}円（入金）"
                if tx.direction == "in"
                else f"{tx.amount}円"
            )
            logger.info(
                "[診断] %s | %s | %s | カテゴリ: %s",
                tx.date.strftime("%Y-%m-%d"),
                amount_str,
                tx.merchant,
                tx.category,
            )
        for tx in to_process:
            detector.mark_processed(tx)
        logger.info("ドライラン完了")
        logger.info("アプリケーションを終了します")
        return

    failed_records = []
    success_count = 0

    try:
        with MFRegistrar(config, logger) as registrar:
            for tx in to_process:
                try:
                    registrar.register(tx)
                    detector.mark_processed(tx)
                    success_count += 1
                    logger.info(
                        "登録完了: %s | %d円 | %s",
                        tx.date.strftime("%Y-%m-%d"),
                        tx.amount,
                        tx.merchant,
                    )
                except Exception as e:
                    failed_records.append(tx)
                    logger.error(
                        "登録失敗: %s | %d円 | %s | %s",
                        tx.date.strftime("%Y-%m-%d"),
                        tx.amount,
                        tx.merchant,
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
        logger.info("エラーCSV: %s", error_csv_path)

    logger.info("アプリケーションを終了します")


if __name__ == "__main__":
    main()
