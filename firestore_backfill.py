"""Firestore の重複履歴へ date_bucket を backfill するユーティリティ。"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.config_loader import CONFIG_ENV_VAR, load_config, resolve_config_path
from src.constants import AppConstants
from src.duplicate_detector import GCloudDuplicateDetector, build_date_bucket

_KEY_DATETIME = "datetime"
_KEY_DATE_BUCKET = "date_bucket"
_WRITE_BATCH_SIZE = 500
_LOG_FORMAT = "[%(levelname)s] %(message)s"
_MSG_BACKEND_REQUIRED = (
    'duplicate_detection.backend: "gcloud" を設定してから実行してください。'
)
_MSG_START = "Firestore date_bucket backfill を開始します"
_MSG_SUMMARY = "走査 %d件 / 更新対象 %d件 / スキップ %d件"
_MSG_SUMMARY_DRY_RUN = "dry-run 完了: 走査 %d件 / 更新予定 %d件 / スキップ %d件"
_MSG_INVALID_DATETIME = "datetime が不正なためスキップしました: %s"
_MSG_FAILED = "Firestore date_bucket backfill に失敗しました"
_EXIT_FAILURE = 1
_CLI_HELP_CONFIG = (
    "config.yml のパス。省略時は --config > 環境変数 "
    f"{CONFIG_ENV_VAR} > カレントディレクトリ > モジュール同居の順に探索します。"
)


@dataclass(slots=True)
class BackfillSummary:
    scanned_count: int
    updated_count: int
    skipped_count: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 引数を解釈する。"""
    parser = argparse.ArgumentParser(
        description="Firestore の既存ドキュメントへ date_bucket を補完します。",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=_CLI_HELP_CONFIG,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="更新せず、対象件数だけを集計します。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="先頭から処理する最大件数。検証用です。",
    )
    return parser.parse_args(argv)


def _load_gcloud_detector(config_path: Path) -> GCloudDuplicateDetector:
    config = load_config(config_path)
    if config.duplicate_detection.backend != AppConstants.BACKEND_GCLOUD:
        raise ValueError(_MSG_BACKEND_REQUIRED)
    return GCloudDuplicateDetector(config)


def backfill_date_buckets(
    detector: GCloudDuplicateDetector,
    logger: logging.Logger,
    *,
    dry_run: bool,
    limit: int | None,
) -> BackfillSummary:
    """既存ドキュメントへ date_bucket を補完する。"""
    collection = detector.collection()
    batch = None if dry_run else detector.batch()
    pending_writes = 0
    scanned_count = 0
    updated_count = 0
    skipped_count = 0

    for snapshot in collection.stream():
        if limit is not None and scanned_count >= limit:
            break

        scanned_count += 1
        data = snapshot.to_dict()
        datetime_raw = data.get(_KEY_DATETIME)
        if not isinstance(datetime_raw, str) or not datetime_raw.strip():
            skipped_count += 1
            logger.warning(_MSG_INVALID_DATETIME, snapshot.id)
            continue

        try:
            date_bucket = build_date_bucket(datetime.fromisoformat(datetime_raw))
        except ValueError:
            skipped_count += 1
            logger.warning(_MSG_INVALID_DATETIME, snapshot.id)
            continue

        if data.get(_KEY_DATE_BUCKET) == date_bucket:
            continue

        updated_count += 1
        if dry_run:
            continue

        batch.set(snapshot.reference, {_KEY_DATE_BUCKET: date_bucket}, merge=True)
        pending_writes += 1

        if pending_writes >= _WRITE_BATCH_SIZE:
            batch.commit()
            batch = detector.batch()
            pending_writes = 0

    if not dry_run and pending_writes > 0:
        batch.commit()

    return BackfillSummary(
        scanned_count=scanned_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
    )


def main(argv: list[str] | None = None) -> None:
    """date_bucket backfill CLI のエントリーポイント。"""
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    logger = logging.getLogger(__name__)
    args = parse_args(argv)
    config_path = resolve_config_path(
        args.config,
        module_dir=Path(__file__).parent,
    )

    try:
        detector = _load_gcloud_detector(config_path)
        logger.info(_MSG_START)
        summary = backfill_date_buckets(
            detector,
            logger,
            dry_run=args.dry_run,
            limit=args.limit,
        )
    except Exception:
        logger.exception(_MSG_FAILED)
        sys.exit(_EXIT_FAILURE)

    if args.dry_run:
        logger.info(
            _MSG_SUMMARY_DRY_RUN,
            summary.scanned_count,
            summary.updated_count,
            summary.skipped_count,
        )
        return

    logger.info(
        _MSG_SUMMARY,
        summary.scanned_count,
        summary.updated_count,
        summary.skipped_count,
    )


if __name__ == "__main__":
    main()
