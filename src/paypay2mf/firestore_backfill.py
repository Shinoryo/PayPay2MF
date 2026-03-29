"""Firestore の重複履歴へ date_bucket を backfill するユーティリティ。"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from paypay2mf.config_loader import CONFIG_ENV_VAR, resolve_config_path
from paypay2mf.constants import AppConstants
from paypay2mf.duplicate_detector import GCloudDuplicateDetector, build_date_bucket
from paypay2mf.models import DuplicateDetectionConfig

_KEY_DATETIME = "datetime"
_KEY_DATE_BUCKET = "date_bucket"
_KEY_DUPLICATE_DETECTION = "duplicate_detection"
_KEY_DD_BACKEND = "backend"
_KEY_DD_TOLERANCE_SECONDS = "tolerance_seconds"
_KEY_GCLOUD_CREDENTIALS_PATH = "gcloud_credentials_path"
_WRITE_BATCH_SIZE = 500
_LOG_FORMAT = "[%(levelname)s] %(message)s"
_MSG_BACKEND_REQUIRED = (
    'duplicate_detection.backend: "gcloud" を設定してから実行してください。'
)
_MSG_CONFIG_NOT_FOUND = "config.yml が見つかりません: {path}"
_MSG_CONFIG_ROOT_TYPE = "config.yml のルート要素は object で指定してください。"
_MSG_CONFIG_YAML_INVALID = "config.yml の YAML 構文が不正です: {detail}"
_MSG_DUPLICATE_DETECTION_TYPE = "duplicate_detection は object で指定してください。"
_MSG_GCLOUD_CREDS_REQUIRED = (
    'duplicate_detection.backend: "gcloud" の場合は '
    "gcloud_credentials_path の指定が必要です。"
)
_MSG_GCLOUD_CREDS_NOT_EXIST = "gcloud_credentials_path のファイルが存在しません: {path}"
_MSG_DUPLICATE_TOLERANCE_TYPE = (
    "duplicate_detection.tolerance_seconds には整数を指定してください。"
)
_MSG_DUPLICATE_TOLERANCE_RANGE = (
    "duplicate_detection.tolerance_seconds には 0 以上の整数を指定してください: {value}"
)
_MSG_LIMIT_NON_NEGATIVE = "--limit には 0 以上の整数を指定してください。"
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


@dataclass(frozen=True, slots=True)
class _BackfillDetectorConfig:
    gcloud_credentials_path: Path
    duplicate_detection: DuplicateDetectionConfig
    dry_run: bool = False


def _parse_non_negative_int(raw_value: str) -> int:
    """argparse 用の非負整数パーサー。"""
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError(_MSG_LIMIT_NON_NEGATIVE)
    return value


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
        type=_parse_non_negative_int,
        default=None,
        help="先頭から処理する最大件数。検証用です。",
    )
    return parser.parse_args(argv)


def _load_gcloud_detector(config_path: Path) -> GCloudDuplicateDetector:
    config = _load_backfill_config(config_path)
    if config.duplicate_detection.backend != AppConstants.BACKEND_GCLOUD:
        raise ValueError(_MSG_BACKEND_REQUIRED)
    return GCloudDuplicateDetector(
        credentials_path=config.gcloud_credentials_path,
        tolerance_seconds=config.duplicate_detection.tolerance_seconds,
        dry_run=config.dry_run,
    )


def _load_backfill_config(config_path: Path) -> _BackfillDetectorConfig:
    raw = _load_raw_config(config_path)
    duplicate_detection_section = _get_duplicate_detection_section(raw)
    _validate_backfill_backend(duplicate_detection_section)
    try:
        tolerance = _get_tolerance_seconds(duplicate_detection_section)
    except TypeError as exc:
        raise ValueError(str(exc)) from exc
    credentials_path = _resolve_gcloud_credentials_path(raw, config_path.parent)

    return _BackfillDetectorConfig(
        gcloud_credentials_path=credentials_path,
        duplicate_detection=DuplicateDetectionConfig(
            backend=AppConstants.BACKEND_GCLOUD,
            tolerance_seconds=tolerance,
        ),
    )


def _load_raw_config(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        raise FileNotFoundError(_MSG_CONFIG_NOT_FOUND.format(path=config_path))

    try:
        with config_path.open(encoding=AppConstants.DEFAULT_TEXT_ENCODING) as file_obj:
            loaded = yaml.safe_load(file_obj)
    except yaml.YAMLError as exc:
        raise ValueError(_MSG_CONFIG_YAML_INVALID.format(detail=str(exc))) from exc

    if loaded is None:
        return {}
    if isinstance(loaded, dict):
        return loaded
    raise ValueError(_MSG_CONFIG_ROOT_TYPE)


def _get_duplicate_detection_section(raw: dict[str, object]) -> dict[str, object]:
    duplicate_detection = raw.get(_KEY_DUPLICATE_DETECTION)
    if duplicate_detection is None:
        return {}
    if isinstance(duplicate_detection, dict):
        return duplicate_detection
    raise ValueError(_MSG_DUPLICATE_DETECTION_TYPE)


def _validate_backfill_backend(duplicate_detection_section: dict[str, object]) -> None:
    backend = duplicate_detection_section.get(
        _KEY_DD_BACKEND,
        AppConstants.DEFAULT_BACKEND,
    )
    if backend != AppConstants.BACKEND_GCLOUD:
        raise ValueError(_MSG_BACKEND_REQUIRED)


def _get_tolerance_seconds(duplicate_detection_section: dict[str, object]) -> int:
    tolerance = duplicate_detection_section.get(_KEY_DD_TOLERANCE_SECONDS, 60)
    if isinstance(tolerance, bool) or not isinstance(tolerance, int):
        raise TypeError(_MSG_DUPLICATE_TOLERANCE_TYPE)
    if tolerance < 0:
        raise ValueError(_MSG_DUPLICATE_TOLERANCE_RANGE.format(value=tolerance))
    return tolerance


def _resolve_gcloud_credentials_path(
    raw: dict[str, object],
    config_dir: Path,
) -> Path:
    credentials_raw = raw.get(_KEY_GCLOUD_CREDENTIALS_PATH)
    if not isinstance(credentials_raw, str) or not credentials_raw.strip():
        raise ValueError(_MSG_GCLOUD_CREDS_REQUIRED)

    credentials_path = _resolve_path(credentials_raw, config_dir)
    if not credentials_path.exists():
        raise ValueError(_MSG_GCLOUD_CREDS_NOT_EXIST.format(path=credentials_path))
    return credentials_path


def _resolve_path(raw_value: str, config_dir: Path) -> Path:
    candidate = Path(raw_value)
    if candidate.is_absolute():
        return candidate
    return config_dir / candidate


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
            skipped_count += 1
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
