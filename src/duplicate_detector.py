"""重複取引の検知と管理。

LocalDuplicateDetectorおよび
GCloudDuplicateDetectorを提供する。
DuplicateDetector Protocol で共通インタフェースを定義する。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.models import AppConfig, Transaction

from src.constants import AppConstants

# ローカルストア JSON のキー名。
_KEY_TX_IDS = "transaction_ids"
_KEY_FALLBACK = "fallback_keys"
_KEY_DATETIME = "datetime"
_KEY_AMOUNT = "amount"
_KEY_MERCHANT = "merchant"

# Firestore のクエリ構築に使う定数。
_FIRESTORE_EQUALS_OPERATOR = "=="


class DuplicateHistoryError(ValueError):
    """重複履歴ファイルの読込失敗を表す例外。"""


@runtime_checkable
class DuplicateDetector(Protocol):
    """重複検知の共通インタフェース。

    このプロトコルを実装するクラスは is_duplicate と mark_processed を持つ。
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
            return tx.transaction_id in self._data[_KEY_TX_IDS]
        return self._is_duplicate_fallback(tx)

    def mark_processed(self, tx: Transaction) -> None:
        """指定した取引を処理済みとしてマークし、JSON に保存する。

        Args:
            tx: マーク対象の Transaction。
        """
        if self._dry_run:
            return

        if tx.transaction_id:
            if tx.transaction_id not in self._data[_KEY_TX_IDS]:
                self._data[_KEY_TX_IDS].append(tx.transaction_id)
        else:
            self._data[_KEY_FALLBACK].append(
                {
                    _KEY_DATETIME: tx.date.isoformat(),
                    _KEY_AMOUNT: tx.amount,
                    _KEY_MERCHANT: tx.merchant,
                },
            )
        self._save()

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
                    self._data = json.load(f)
            except json.JSONDecodeError as exc:
                backup_path = self._backup_corrupted_store()
                msg = (
                    "processed.json が破損しているため読み込めません。"
                    f"退避先: {backup_path}"
                )
                raise DuplicateHistoryError(msg) from exc

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
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
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

        # fallback: amount + merchant の一致 + datetime 許容幅
        # NOTE T03: Firestore の複合インデックス（amount, merchant）が必要
        query = (
            self._client.collection(self._COLLECTION)
            .where(_KEY_AMOUNT, _FIRESTORE_EQUALS_OPERATOR, tx.amount)
            .where(_KEY_MERCHANT, _FIRESTORE_EQUALS_OPERATOR, tx.merchant)
        )
        for doc in query.stream():
            data = doc.to_dict()
            stored_dt = datetime.fromisoformat(data[_KEY_DATETIME])
            delta = timedelta(seconds=self._tolerance)
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
            {
                _KEY_DATETIME: tx.date.isoformat(),
                _KEY_AMOUNT: tx.amount,
                _KEY_MERCHANT: tx.merchant,
            },
        )


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
