"""重複取引の検知と管理。

LocalDuplicateDetectorおよび
GCloudDuplicateDetectorを提供する。
DuplicateDetector Protocol で共通インタフェースを定義する。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from paypay2mf.models import AppConfig, Transaction

from paypay2mf.constants import AppConstants

# ローカルストア JSON のキー名。
_KEY_ROW_FINGERPRINTS = "row_fingerprints"
_KEY_DATETIME = "datetime"
_KEY_AMOUNT = "amount"
_KEY_MERCHANT = "merchant"
_KEY_ROW_FINGERPRINT = "row_fingerprint"
_KEY_TRANSACTION_ID = "transaction_id"

_MSG_PROCESSED_ROOT_TYPE = "processed.json のルートは object である必要があります"
_MSG_PROCESSED_ROW_FINGERPRINTS_TYPE = "row_fingerprints は list である必要があります"
_MSG_PROCESSED_ROW_FINGERPRINT_ITEM_TYPE = (
    "row_fingerprints の要素は文字列である必要があります"
)
_KEY_DATE_BUCKET = "date_bucket"

# Firestore のクエリ構築に使う定数。
_FIRESTORE_EQUALS_OPERATOR = "=="
_DATE_BUCKET_FORMAT = "%Y%m%d%H%M"
_MSG_GCLOUD_CREDS_REQUIRED = (
    'duplicate_detection.backend: "gcloud" の場合は '
    "gcloud_credentials_path の指定が必要です。"
)
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
        if config.gcloud_credentials_path is None:
            raise DuplicateHistoryError(_MSG_GCLOUD_CREDS_REQUIRED)
        return GCloudDuplicateDetector(
            credentials_path=config.gcloud_credentials_path,
            database_id=config.duplicate_detection.database_id,
            dry_run=config.dry_run,
        )
    return LocalDuplicateDetector(config)


def build_date_bucket(value: datetime) -> str:
    """指定日時を分単位の date_bucket 文字列に変換する。"""
    return value.replace(second=0, microsecond=0).strftime(_DATE_BUCKET_FORMAT)


def build_firestore_duplicate_payload(tx: Transaction) -> dict[str, str | int]:
    """Firestore に保存する重複検知用 payload を組み立てる。"""
    return {
        _KEY_ROW_FINGERPRINT: resolve_row_fingerprint(tx),
        _KEY_DATETIME: tx.date.isoformat(),
        _KEY_AMOUNT: tx.amount,
        _KEY_MERCHANT: tx.merchant,
        _KEY_DATE_BUCKET: build_date_bucket(tx.date),
        _KEY_TRANSACTION_ID: tx.transaction_id or AppConstants.EMPTY_STRING,
    }


def build_firestore_fallback_doc_id(tx: Transaction) -> str:
    """後方互換のために残す fallback doc_id ビルダー。"""
    digest = hashlib.sha256(
        f"{tx.date.isoformat()}|{tx.amount}|{tx.merchant}".encode(
            AppConstants.DEFAULT_TEXT_ENCODING,
        ),
    ).hexdigest()
    return f"fallback_{digest}"


def build_row_fingerprint(  # noqa: PLR0913
    *,
    date_text: str,
    content: str,
    merchant: str,
    out_amount: int,
    in_amount: int,
    method: str,
    payment_type: str,
    user: str,
) -> str:
    """行の正規化フィールドから重複検知用の行指紋（sha256）を生成する。

    csv_parser および重複検知の両方から呼び出す唯一の指紋生成実装。
    """
    raw = json.dumps(
        [
            date_text,
            content,
            merchant,
            str(out_amount),
            str(in_amount),
            method,
            payment_type,
            user,
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode(AppConstants.DEFAULT_TEXT_ENCODING)).hexdigest()


def resolve_row_fingerprint(tx: Transaction) -> str:
    """取引の重複検知に使う行指紋を返す。"""
    if tx.row_fingerprint:
        return tx.row_fingerprint

    date_text = tx.date_text or tx.date.strftime("%Y/%m/%d %H:%M:%S")
    out_amount = tx.amount if tx.direction == AppConstants.DIRECTION_OUT else 0
    in_amount = tx.amount if tx.direction == AppConstants.DIRECTION_IN else 0
    return build_row_fingerprint(
        date_text=date_text,
        content=tx.content,
        merchant=tx.merchant,
        out_amount=out_amount,
        in_amount=in_amount,
        method=tx.method,
        payment_type=tx.payment_type,
        user=tx.user,
    )


def _parse_firestore_datetime(data: object, doc_id: str) -> datetime:
    """Firestore 文書の datetime を検証し、異常を履歴エラーへ正規化する。"""
    if not isinstance(data, dict):
        msg = f"Firestore の重複履歴文書が不正です: paypay_transactions/{doc_id}"
        raise DuplicateHistoryError(msg)

    datetime_raw = data.get(_KEY_DATETIME)
    if not isinstance(datetime_raw, str) or not datetime_raw.strip():
        msg = f"Firestore の重複履歴 datetime が不正です: paypay_transactions/{doc_id}"
        raise DuplicateHistoryError(msg)

    try:
        return datetime.fromisoformat(datetime_raw)
    except ValueError as exc:
        msg = f"Firestore の重複履歴 datetime が不正です: paypay_transactions/{doc_id}"
        raise DuplicateHistoryError(msg) from exc


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
        self._data: dict = {
            _KEY_ROW_FINGERPRINTS: [],
        }
        self._row_fingerprints: set[str] = set()
        self._dirty = False
        self._load()

    def is_duplicate(self, tx: Transaction) -> bool:
        """指定した取引が処理済みかどうかを確認する。

        行指紋が処理済み集合に含まれているかで判定する。

        Args:
            tx: 確認対象の Transaction。

        Returns:
            処理済みと判定すれば True。
        """
        return resolve_row_fingerprint(tx) in self._row_fingerprints

    def mark_processed(self, tx: Transaction) -> None:
        """指定した取引を処理済みとしてマークする。

        Args:
            tx: マーク対象の Transaction。
        """
        if self._dry_run:
            return

        row_fingerprint = resolve_row_fingerprint(tx)
        if row_fingerprint not in self._row_fingerprints:
            self._row_fingerprints.add(row_fingerprint)
            self._data[_KEY_ROW_FINGERPRINTS].append(row_fingerprint)
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
                self._row_fingerprints = set(self._data[_KEY_ROW_FINGERPRINTS])
                self._dirty = False
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                backup_path = self._backup_corrupted_store()
                msg = (
                    "processed.json が破損しているため読み込めません。"
                    f"退避先: {backup_path}"
                )
                raise DuplicateHistoryError(msg) from exc
        else:
            self._row_fingerprints = set(self._data[_KEY_ROW_FINGERPRINTS])

    def _validate_loaded_data(self, loaded_data: object) -> dict:
        if not isinstance(loaded_data, dict):
            raise TypeError(_MSG_PROCESSED_ROOT_TYPE)

        loaded_data.setdefault(_KEY_ROW_FINGERPRINTS, [])

        row_fingerprints = loaded_data[_KEY_ROW_FINGERPRINTS]

        if not isinstance(row_fingerprints, list):
            raise TypeError(_MSG_PROCESSED_ROW_FINGERPRINTS_TYPE)

        for row_fingerprint in row_fingerprints:
            if not isinstance(row_fingerprint, str):
                raise TypeError(_MSG_PROCESSED_ROW_FINGERPRINT_ITEM_TYPE)

        return loaded_data

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
        try:
            self._store_path.replace(backup_path)
        except OSError as exc:
            msg = f"processed.json の退避に失敗しました: {backup_path}"
            raise DuplicateHistoryError(msg) from exc
        return backup_path


class GCloudDuplicateDetector:
    """Google Cloud Firestore を用いた重複検知の実装。

    google-cloud-firestore パッケージが必要。
    """

    _COLLECTION = "paypay_transactions"

    def __init__(
        self,
        *,
        credentials_path: Path,
        database_id: str,
        dry_run: bool,
    ) -> None:
        """GCloudDuplicateDetector を初期化する。

        Firestore クライアントをサービスアカウント認証情報で初期化する。

        Args:
            credentials_path: サービスアカウント JSON のパス。
            database_id: Firestore のデータベース ID。
            dry_run: True の場合は Firestore 書き込みを抑止する。

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

        try:
            creds = service_account.Credentials.from_service_account_file(
                str(credentials_path),
            )
            self._client = _firestore.Client(
                credentials=creds,
                database=database_id,
            )
        except Exception as exc:
            msg = f"GCloud 認証情報の初期化に失敗しました: {credentials_path}"
            raise DuplicateHistoryError(msg) from exc
        self._dry_run = dry_run

    def is_duplicate(self, tx: Transaction) -> bool:
        """指定した取引が Firestore に処理済みとして登録済みかどうかを確認する。

        Args:
            tx: 確認対象の Transaction。

        Returns:
            処理済みと判定すれば True。
        """
        doc = (
            self._client.collection(self._COLLECTION)
            .document(resolve_row_fingerprint(tx))
            .get()
        )
        return doc.exists

    def mark_processed(self, tx: Transaction) -> None:
        """指定した取引を Firestore に処理済みとして登録する。

        Args:
            tx: マーク対象の Transaction。
        """
        if self._dry_run:
            return

        doc_id = resolve_row_fingerprint(tx)
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
    base = config.log_settings.logs_dir
    if base is None:
        base_dir = config.runtime_base_dir or Path.cwd()
        base = base_dir / AppConstants.DEFAULT_LOGS_DIR
    return base / AppConstants.PROCESSED_FILENAME
