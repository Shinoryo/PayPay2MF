"""重複取引の検知と管理。

LocalDuplicateDetectorおよび
GCloudDuplicateDetectorを提供する。
DuplicateDetector Protocol で共通インタフェースを定義する。
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from paypay2mf.models import AppConfig, Transaction

from paypay2mf.constants import AppConstants

# ローカルストア JSON のキー名。
_KEY_TX_IDS = "transaction_ids"
_KEY_FALLBACK = "fallback_keys"
_KEY_DATETIME = "datetime"
_KEY_AMOUNT = "amount"
_KEY_MERCHANT = "merchant"
_KEY_DATE_BUCKET = "date_bucket"

# Firestore のクエリ構築に使う定数。
_FIRESTORE_EQUALS_OPERATOR = "=="
_DATE_BUCKET_FORMAT = "%Y%m%d%H%M"
_MSG_PROCESSED_SAVE_FAILED = "processed.json の保存に失敗しました"


class DuplicateHistoryError(ValueError):
    """重複履歴ファイルの読込失敗を表す例外。"""


class DuplicateHistorySaveError(OSError):
    """重複履歴ファイルの保存失敗を表す例外。"""


@runtime_checkable
class DuplicateDetector(Protocol):
    """重複検知の共通インタフェース。

    このプロトコルを実装するクラスは is_duplicate、mark_processed、flush を持つ。
    """

    def is_duplicate(self, tx: Transaction) -> bool:
        """指定した取引が処理済みかどうかを確認する。

        Args:
            tx: 確認対象の Transaction。

        Returns:
            処理済みであれば True。
        """
        ...

    def mark_processed(self, tx: Transaction) -> None:
        """指定した取引を処理済みとしてマークする。

        Args:
            tx: マーク対象の Transaction。
        """
        ...

    def flush(self) -> None:
        """保留中の処理済みデータを永続化する。"""
        ...


def create_detector(config: AppConfig) -> DuplicateDetector:
    """設定に基づいて適切な DuplicateDetector を生成して返す。

    Args:
        config: アプリケーション設定。

    Returns:
        LocalDuplicateDetector または GCloudDuplicateDetector のインスタンス。
    """
    if config.duplicate_detection.backend == AppConstants.BACKEND_GCLOUD:
        return GCloudDuplicateDetector(config)
    return LocalDuplicateDetector(config)


def build_date_bucket(value: datetime) -> str:
    """指定日時を分単位の date_bucket 文字列に変換する。"""
    return value.replace(second=0, microsecond=0).strftime(_DATE_BUCKET_FORMAT)


def list_date_bucket_candidates(
    value: datetime,
    tolerance_seconds: int,
) -> list[str]:
    """許容幅に含まれる date_bucket 候補を列挙する。"""
    bounded_tolerance = max(tolerance_seconds, 0)
    lower_bound = value - timedelta(seconds=bounded_tolerance)
    upper_bound = value + timedelta(seconds=bounded_tolerance)
    current_bucket = lower_bound.replace(second=0, microsecond=0)
    last_bucket = upper_bound.replace(second=0, microsecond=0)

    buckets: list[str] = []
    while current_bucket <= last_bucket:
        buckets.append(build_date_bucket(current_bucket))
        current_bucket += timedelta(minutes=1)
    return buckets


def build_firestore_duplicate_payload(tx: Transaction) -> dict[str, str | int]:
    """Firestore に保存する重複検知用 payload を組み立てる。"""
    return {
        _KEY_DATETIME: tx.date.isoformat(),
        _KEY_AMOUNT: tx.amount,
        _KEY_MERCHANT: tx.merchant,
        _KEY_DATE_BUCKET: build_date_bucket(tx.date),
    }


class LocalDuplicateDetector:
    """JSON ファイルを用いたローカル重複検知の実装。

    処理済み取引の情報を ``<logs_dir>/processed.json`` に保存する。
    インスタンス生成時に既存のファイルを自動で読み込む。
    """

    def __init__(self, config: AppConfig) -> None:
        """初期化する。

        処理済み取引のデータを JSON ファイルから読み込む。

        Args:
            config: アプリケーション設定。
        """
        self._store_path = _get_store_path(config)
        self._dry_run = config.dry_run
        self._tolerance = config.duplicate_detection.tolerance_seconds
        self._data: dict = {
            _KEY_TX_IDS: [],
            _KEY_FALLBACK: [],
        }
        self._tx_ids: set[str] = set()
        self._dirty = False
        self._load()

    def is_duplicate(self, tx: Transaction) -> bool:
        """指定した取引が処理済みかどうかを確認する。

        transaction_id がある場合はそのまま一致判定を行う。
        ない場合は _is_duplicate_fallback でフォールバック判定を行う。

        Args:
            tx: 確認対象の Transaction。

        Returns:
            処理済みと判定すれば True。
        """
        if tx.transaction_id:
            return tx.transaction_id in self._tx_ids
        return self._is_duplicate_fallback(tx)

    def mark_processed(self, tx: Transaction) -> None:
        """指定した取引を処理済みとしてマークする。

        Args:
            tx: マーク対象の Transaction。
        """
        if self._dry_run:
            return

        if tx.transaction_id:
            if tx.transaction_id not in self._tx_ids:
                self._tx_ids.add(tx.transaction_id)
                self._data[_KEY_TX_IDS].append(tx.transaction_id)
                self._dirty = True
        else:
            self._data[_KEY_FALLBACK].append(
                {
                    _KEY_DATETIME: tx.date.isoformat(),
                    _KEY_AMOUNT: tx.amount,
                    _KEY_MERCHANT: tx.merchant,
                },
            )
            self._dirty = True

    def flush(self) -> None:
        """保留中の処理済みデータを JSON ファイルへ書き出す。"""
        if self._dry_run or not self._dirty:
            return

        try:
            self._save()
        except OSError as exc:
            raise DuplicateHistorySaveError(_MSG_PROCESSED_SAVE_FAILED) from exc
        self._dirty = False

    def _is_duplicate_fallback(self, tx: Transaction) -> bool:
        """取引番号欠損時のフォールバック重複判定。

        保存済みの欠損タプルの中で、日時差が
        tolerance_seconds 以内で金額・取引先が一致する項目を重複と判定する。

        Args:
            tx: 確認対象の Transaction。

        Returns:
            重複と判定すれば True。
        """
        for entry in self._data.get(_KEY_FALLBACK, []):
            stored_dt = datetime.fromisoformat(entry[_KEY_DATETIME])
            if (
                entry[_KEY_AMOUNT] == tx.amount
                and entry[_KEY_MERCHANT] == tx.merchant
                and abs((tx.date - stored_dt).total_seconds()) <= self._tolerance
            ):
                return True
        return False

    def _load(self) -> None:
        """JSON ファイルから処理済みデータを読み込む。

        ファイルが存在しない場合は空の状態のままにする。
        """
        if self._store_path.exists():
            try:
                with self._store_path.open(
                    encoding=AppConstants.DEFAULT_TEXT_ENCODING,
                ) as f:
                    self._data = self._validate_loaded_data(json.load(f))
                self._tx_ids = set(self._data[_KEY_TX_IDS])
                self._dirty = False
            except (json.JSONDecodeError, ValueError) as exc:
                backup_path = self._backup_corrupted_store()
                msg = (
                    "processed.json が破損しているため読み込めません。"
                    f"退避先: {backup_path}"
                )
                raise DuplicateHistoryError(msg) from exc
        else:
            self._tx_ids = set(self._data[_KEY_TX_IDS])

    def _validate_loaded_data(self, loaded_data: object) -> dict:
        if not isinstance(loaded_data, dict):
            raise ValueError("processed.json のルートは object である必要があります")

        loaded_data.setdefault(_KEY_TX_IDS, [])
        loaded_data.setdefault(_KEY_FALLBACK, [])

        transaction_ids = loaded_data[_KEY_TX_IDS]
        fallback_entries = loaded_data[_KEY_FALLBACK]

        if not isinstance(transaction_ids, list):
            raise ValueError("transaction_ids は list である必要があります")
        if not isinstance(fallback_entries, list):
            raise ValueError("fallback_keys は list である必要があります")

        for transaction_id in transaction_ids:
            if not isinstance(transaction_id, str):
                raise ValueError("transaction_ids の要素は文字列である必要があります")

        for entry in fallback_entries:
            self._validate_fallback_entry(entry)

        return loaded_data

    def _validate_fallback_entry(self, entry: object) -> None:
        if not isinstance(entry, dict):
            raise ValueError("fallback_keys の要素は object である必要があります")

        datetime_value = entry.get(_KEY_DATETIME)
        amount_value = entry.get(_KEY_AMOUNT)
        merchant_value = entry.get(_KEY_MERCHANT)

        if not isinstance(datetime_value, str):
            raise ValueError("fallback_keys.datetime は文字列である必要があります")
        if not isinstance(amount_value, int) or isinstance(amount_value, bool):
            raise ValueError("fallback_keys.amount は整数である必要があります")
        if not isinstance(merchant_value, str):
            raise ValueError("fallback_keys.merchant は文字列である必要があります")

    def _save(self) -> None:
        """処理済みデータを JSON ファイルに書き出す。"""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._store_path.with_name(f"{self._store_path.name}.tmp")
        try:
            with temp_path.open("w", encoding=AppConstants.DEFAULT_TEXT_ENCODING) as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            temp_path.replace(self._store_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

    def _backup_corrupted_store(self) -> Path:
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S_%f")
        backup_path = self._store_path.with_name(
            f"{self._store_path.stem}.corrupted_{timestamp}{self._store_path.suffix}",
        )
        self._store_path.replace(backup_path)
        return backup_path


class GCloudDuplicateDetector:
    """Google Cloud Firestore を用いた重複検知の実装。

    google-cloud-firestore パッケージが必要。
    """

    _COLLECTION = "paypay_transactions"

    def __init__(self, config: AppConfig) -> None:
        """GCloudDuplicateDetector を初期化する。

        Firestore クライアントをサービスアカウント認証情報で初期化する。

        Args:
            config: アプリケーション設定。
                gcloud_credentials_path が設定されていることを想定する。

        Raises:
            ImportError: google-cloud-firestore がインストールされていない場合。
        """
        try:
            from google.cloud import (  # noqa: I001, PLC0415
                firestore as _firestore,  # type: ignore[import-untyped]
            )
            from google.oauth2 import service_account  # type: ignore[import-untyped]  # noqa: PLC0415
        except ImportError as e:
            msg = (
                "google-cloud-firestore がインストールされていません。"
                "pip install 'paypay2mf[gcloud]' を実行してください。"
            )
            raise ImportError(msg) from e

        creds = service_account.Credentials.from_service_account_file(
            str(config.gcloud_credentials_path),
        )
        self._client = _firestore.Client(credentials=creds)
        self._dry_run = config.dry_run
        self._tolerance = config.duplicate_detection.tolerance_seconds

    def is_duplicate(self, tx: Transaction) -> bool:
        """指定した取引が Firestore に処理済みとして登録済みかどうかを確認する。

        Args:
            tx: 確認対象の Transaction。

        Returns:
            処理済みと判定すれば True。
        """
        if tx.transaction_id:
            doc = (
                self._client.collection(self._COLLECTION)
                .document(tx.transaction_id)
                .get()
            )
            return doc.exists

        # fallback: amount + merchant + date_bucket で候補を絞り込んだうえで
        # datetime と tolerance_seconds で最終判定する。
        # NOTE T03: Firestore の複合インデックス（amount, merchant, date_bucket）が必要
        collection = self._client.collection(self._COLLECTION)
        delta = timedelta(seconds=self._tolerance)

        for date_bucket in list_date_bucket_candidates(tx.date, self._tolerance):
            query = (
                collection.where(_KEY_AMOUNT, _FIRESTORE_EQUALS_OPERATOR, tx.amount)
                .where(_KEY_MERCHANT, _FIRESTORE_EQUALS_OPERATOR, tx.merchant)
                .where(_KEY_DATE_BUCKET, _FIRESTORE_EQUALS_OPERATOR, date_bucket)
            )
            for doc in query.stream():
                data = doc.to_dict()
                stored_dt = datetime.fromisoformat(data[_KEY_DATETIME])
                if abs(tx.date - stored_dt) <= delta:
                    return True
        return False

    def mark_processed(self, tx: Transaction) -> None:
        """指定した取引を Firestore に処理済みとして登録する。

        Args:
            tx: マーク対象の Transaction。
        """
        if self._dry_run:
            return

        if tx.transaction_id:
            doc_id = tx.transaction_id
        else:
            doc_id = (
                f"{tx.amount}_{tx.merchant}_"
                f"{tx.date.strftime(AppConstants.DUPLICATE_KEY_DATE_FORMAT)}"
            )
        self._client.collection(self._COLLECTION).document(doc_id).set(
            build_firestore_duplicate_payload(tx)
        )

    @property
    def client(self) -> object:
        """Firestore クライアントを返す。"""
        return self._client

    def collection(self) -> object:
        """重複履歴コレクション参照を返す。"""
        return self._client.collection(self._COLLECTION)

    def batch(self) -> object:
        """Firestore への書き込みバッチを返す。"""
        return self._client.batch()

    def flush(self) -> None:
        """Firestore バックエンドでは追加の flush は不要。"""


def _get_store_path(config: AppConfig) -> Path:
    """LocalDuplicateDetector が使用する JSON ファイルのパスを返す。

    Args:
        config: アプリケーション設定。

    Returns:
        processed.json の Path。
    """
    base = (
        config.log_settings.logs_dir
        or Path(__file__).parent.parent / AppConstants.DEFAULT_LOGS_DIR
    )
    return base / AppConstants.PROCESSED_FILENAME
