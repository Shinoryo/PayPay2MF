"""duplicate_detector モジュールのテスト。

対応テストケース:
    TC-04-01: 取引番号による重複検知
    TC-04-02: 取引番号欠損時のフォールバック重複検知
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from paypay2mf.constants import AppConstants
from paypay2mf.duplicate_detector import (
    DuplicateHistoryError,
    GCloudDuplicateDetector,
    LocalDuplicateDetector,
    build_date_bucket,
    build_firestore_fallback_doc_id,
    create_detector,
)

if TYPE_CHECKING:
    from pathlib import Path

    from paypay2mf.models import AppConfig


class _FakeFirestoreDocumentSnapshot:
    def __init__(
        self,
        *,
        exists: bool,
        data: dict | None = None,
        doc_id: str | None = None,
        reference: _FakeFirestoreDocumentReference | None = None,
    ) -> None:
        self.exists = exists
        self._data = data or {}
        self.id = doc_id or AppConstants.EMPTY_STRING
        self.reference = reference

    def to_dict(self) -> dict:
        return dict(self._data)


class _FakeFirestoreDocumentReference:
    def __init__(self, store: dict[str, dict], doc_id: str) -> None:
        self._store = store
        self._doc_id = doc_id

    @property
    def doc_id(self) -> str:
        return self._doc_id

    def get(self) -> _FakeFirestoreDocumentSnapshot:
        data = self._store.get(self._doc_id)
        return _FakeFirestoreDocumentSnapshot(
            exists=data is not None,
            data=data,
            doc_id=self._doc_id,
            reference=self,
        )

    def set(self, data: dict) -> None:
        self._store[self._doc_id] = dict(data)


class _FakeFirestoreQuery:
    def __init__(
        self,
        store: dict[str, dict],
        filters: list[tuple[str, object]],
        query_log: list[tuple[tuple[str, object], ...]],
    ) -> None:
        self._store = store
        self._filters = filters
        self._query_log = query_log

    def where(self, field: str, _operator: str, value: object) -> _FakeFirestoreQuery:
        return _FakeFirestoreQuery(
            self._store,
            [*self._filters, (field, value)],
            self._query_log,
        )

    def stream(self) -> list[_FakeFirestoreDocumentSnapshot]:
        self._query_log.append(tuple(self._filters))
        matches: list[_FakeFirestoreDocumentSnapshot] = []
        for doc_id, data in self._store.items():
            if all(data.get(field) == value for field, value in self._filters):
                reference = _FakeFirestoreDocumentReference(self._store, doc_id)
                matches.append(
                    _FakeFirestoreDocumentSnapshot(
                        exists=True,
                        data=data,
                        doc_id=doc_id,
                        reference=reference,
                    )
                )
        return matches


class _FakeFirestoreBatch:
    def __init__(
        self,
        store: dict[str, dict],
        commit_log: list[list[dict[str, object]]],
    ) -> None:
        self._store = store
        self._commit_log = commit_log
        self._pending_operations: list[dict[str, object]] = []

    def set(
        self,
        reference: _FakeFirestoreDocumentReference,
        data: dict,
        *,
        merge: bool = False,
    ) -> None:
        self._pending_operations.append(
            {
                "reference": reference,
                "data": dict(data),
                "merge": merge,
            }
        )

    def commit(self) -> None:
        committed_operations: list[dict[str, object]] = []
        for operation in self._pending_operations:
            reference = operation["reference"]
            data = dict(operation["data"])
            merge = bool(operation["merge"])
            assert isinstance(reference, _FakeFirestoreDocumentReference)
            if merge:
                existing = dict(self._store.get(reference.doc_id, {}))
                existing.update(data)
                self._store[reference.doc_id] = existing
            else:
                self._store[reference.doc_id] = data
            committed_operations.append(
                {
                    "doc_id": reference.doc_id,
                    "data": data,
                    "merge": merge,
                }
            )
        self._commit_log.append(committed_operations)
        self._pending_operations = []


class _FakeFirestoreCollection:
    def __init__(
        self,
        store: dict[str, dict],
        query_log: list[tuple[tuple[str, object], ...]],
    ) -> None:
        self._store = store
        self._query_log = query_log

    def document(self, doc_id: str) -> _FakeFirestoreDocumentReference:
        return _FakeFirestoreDocumentReference(self._store, doc_id)

    def stream(self) -> list[_FakeFirestoreDocumentSnapshot]:
        return [
            _FakeFirestoreDocumentSnapshot(
                exists=True,
                data=data,
                doc_id=doc_id,
                reference=_FakeFirestoreDocumentReference(self._store, doc_id),
            )
            for doc_id, data in self._store.items()
        ]

    def where(self, field: str, _operator: str, value: object) -> _FakeFirestoreQuery:
        return _FakeFirestoreQuery(
            self._store,
            [(field, value)],
            self._query_log,
        )


class _FakeFirestoreClient:
    def __init__(self, *, credentials: object) -> None:
        self.credentials = credentials
        self.store: dict[str, dict] = {}
        self.executed_queries: list[tuple[tuple[str, object], ...]] = []
        self.batch_commits: list[list[dict[str, object]]] = []

    def collection(self, _name: str) -> _FakeFirestoreCollection:
        return _FakeFirestoreCollection(self.store, self.executed_queries)

    def batch(self) -> _FakeFirestoreBatch:
        return _FakeFirestoreBatch(self.store, self.batch_commits)


def _install_fake_gcloud_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    google_module = types.ModuleType("google")
    cloud_module = types.ModuleType("google.cloud")
    firestore_module = types.ModuleType("google.cloud.firestore")
    oauth2_module = types.ModuleType("google.oauth2")
    service_account_module = types.ModuleType("google.oauth2.service_account")

    class _FakeCredentials:
        @staticmethod
        def from_service_account_file(path: str) -> tuple[str, str]:
            return ("creds", path)

    firestore_module.Client = _FakeFirestoreClient
    service_account_module.Credentials = _FakeCredentials
    cloud_module.firestore = firestore_module
    oauth2_module.service_account = service_account_module
    google_module.cloud = cloud_module
    google_module.oauth2 = oauth2_module

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.firestore", firestore_module)
    monkeypatch.setitem(sys.modules, "google.oauth2", oauth2_module)
    monkeypatch.setitem(
        sys.modules,
        "google.oauth2.service_account",
        service_account_module,
    )


def _build_gcloud_config(
    tmp_path: Path,
    app_config_factory,
    *,
    dry_run: bool = False,
) -> AppConfig:
    config = app_config_factory(tmp_path, dry_run=dry_run, input_csv_name="dummy.csv")
    credentials_file = tmp_path / "service-account.json"
    credentials_file.write_text("{}", encoding=AppConstants.DEFAULT_TEXT_ENCODING)
    config.duplicate_detection.backend = AppConstants.BACKEND_GCLOUD
    config.gcloud_credentials_path = credentials_file
    return config


# TC-04-01: 取引番号による重複検知
def test_local_duplicate_by_id(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """TC-04-01: 同一 transaction_id の取引が重複として検知されることを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)

    tx = transaction_factory(transaction_id="TX001")
    assert detector.is_duplicate(tx) is False

    detector.mark_processed(tx)
    assert detector.is_duplicate(tx) is True


# TC-04-02: 取引番号欠損時のフォールバック（日時+金額+取引先）
def test_local_duplicate_fallback(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """TC-04-02: transaction_id が None の場合に日時・金額・取引先でフォールバック判定がされることを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)

    tx = transaction_factory(transaction_id=None, merchant="テスト商店", amount=500)
    assert detector.is_duplicate(tx) is False

    detector.mark_processed(tx)
    assert detector.is_duplicate(tx) is True


# 重複なし（別取引番号）
def test_local_no_duplicate(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """別の transaction_id を持つ取引が重複として判定されないことを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)

    tx1 = transaction_factory(transaction_id="TX001")
    tx2 = transaction_factory(transaction_id="TX002")

    detector.mark_processed(tx1)
    assert detector.is_duplicate(tx2) is False


# mark_processed が JSON に永続化される
def test_local_persistence(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """mark_processed の結果が JSON ファイルに永続化され、新しいインスタンスでも読み込まれることを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")

    detector1 = LocalDuplicateDetector(config)
    tx = transaction_factory(transaction_id="TX_PERSIST")
    detector1.mark_processed(tx)
    detector1.flush()

    # 新しいインスタンスで読み込み → 重複として検知
    detector2 = LocalDuplicateDetector(config)
    assert detector2.is_duplicate(tx) is True


def test_local_mark_processed_buffers_writes_until_flush(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """mark_processed はメモリ更新だけを行い、flush 時に一度だけ保存する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)
    dump_mock = Mock(wraps=json.dump)
    monkeypatch.setattr("paypay2mf.duplicate_detector.json.dump", dump_mock)

    detector.mark_processed(transaction_factory(transaction_id="TX001"))
    detector.mark_processed(transaction_factory(transaction_id="TX002"))

    assert detector.is_duplicate(transaction_factory(transaction_id="TX001")) is True
    assert detector.is_duplicate(transaction_factory(transaction_id="TX002")) is True
    assert dump_mock.call_count == 0
    assert (tmp_path / AppConstants.PROCESSED_FILENAME).exists() is False

    detector.flush()

    assert dump_mock.call_count == 1
    stored = json.loads(
        (tmp_path / AppConstants.PROCESSED_FILENAME).read_text(
            encoding=AppConstants.DEFAULT_TEXT_ENCODING,
        )
    )
    assert stored["transaction_ids"] == ["TX001", "TX002"]


def test_local_corrupted_history_is_backed_up_and_raises_explicit_error(
    tmp_path: Path,
    app_config_factory,
) -> None:
    """破損した processed.json は退避され、明示エラーに変換されることを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    processed_file = tmp_path / AppConstants.PROCESSED_FILENAME
    corrupted_payload = "{broken json}"
    processed_file.write_text(
        corrupted_payload,
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )

    with pytest.raises(DuplicateHistoryError, match=r"processed\.json"):
        LocalDuplicateDetector(config)

    backup_files = list(tmp_path.glob("processed.corrupted_*.json"))
    assert len(backup_files) == 1
    assert processed_file.exists() is False
    assert (
        backup_files[0].read_text(encoding=AppConstants.DEFAULT_TEXT_ENCODING)
        == corrupted_payload
    )


@pytest.mark.parametrize(
    ("payload", "expected_backup_payload"),
    [
        ([], []),
        (
            {"transaction_ids": {}, "fallback_keys": []},
            {
                "transaction_ids": {},
                "fallback_keys": [],
            },
        ),
        (
            {"transaction_ids": [], "fallback_keys": {}},
            {
                "transaction_ids": [],
                "fallback_keys": {},
            },
        ),
        (
            {
                "transaction_ids": [],
                "fallback_keys": [
                    {
                        "datetime": "2025-01-01T12:00:00",
                        "amount": "100",
                        "merchant": "broken",
                    }
                ],
            },
            {
                "transaction_ids": [],
                "fallback_keys": [
                    {
                        "datetime": "2025-01-01T12:00:00",
                        "amount": "100",
                        "merchant": "broken",
                    }
                ],
            },
        ),
        (
            {
                "transaction_ids": [123],
                "fallback_keys": [],
            },
            {
                "transaction_ids": [123],
                "fallback_keys": [],
            },
        ),
        (
            {
                "transaction_ids": [],
                "fallback_keys": [
                    {
                        "datetime": 123,
                        "amount": 100,
                        "merchant": "broken",
                    }
                ],
            },
            {
                "transaction_ids": [],
                "fallback_keys": [
                    {
                        "datetime": 123,
                        "amount": 100,
                        "merchant": "broken",
                    }
                ],
            },
        ),
        (
            {
                "transaction_ids": [],
                "fallback_keys": [
                    {
                        "datetime": "2025-01-01T12:00:00",
                        "amount": 100,
                        "merchant": 123,
                    }
                ],
            },
            {
                "transaction_ids": [],
                "fallback_keys": [
                    {
                        "datetime": "2025-01-01T12:00:00",
                        "amount": 100,
                        "merchant": 123,
                    }
                ],
            },
        ),
        (
            {
                "transaction_ids": [],
                "fallback_keys": [
                    {
                        "datetime": "2025-01-01T12:00:00",
                        "merchant": "broken",
                    }
                ],
            },
            {
                "transaction_ids": [],
                "fallback_keys": [
                    {
                        "datetime": "2025-01-01T12:00:00",
                        "merchant": "broken",
                    }
                ],
            },
        ),
    ],
    ids=[
        "root_list",
        "transaction_ids_not_list",
        "fallback_keys_not_list",
        "fallback_entry_invalid_amount",
        "transaction_id_item_not_string",
        "fallback_entry_invalid_datetime",
        "fallback_entry_invalid_merchant",
        "fallback_entry_missing_amount",
    ],
)
def test_local_corrupted_history_schema_is_backed_up_and_raises_explicit_error(
    tmp_path: Path,
    app_config_factory,
    payload: object,
    expected_backup_payload: object,
) -> None:
    """不正スキーマの processed.json は退避され、明示エラーに変換される。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    processed_file = tmp_path / AppConstants.PROCESSED_FILENAME
    processed_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )

    with pytest.raises(DuplicateHistoryError, match=r"processed\.json"):
        LocalDuplicateDetector(config)

    backup_files = list(tmp_path.glob("processed.corrupted_*.json"))
    assert len(backup_files) == 1
    assert processed_file.exists() is False
    assert (
        json.loads(
            backup_files[0].read_text(encoding=AppConstants.DEFAULT_TEXT_ENCODING)
        )
        == expected_backup_payload
    )


def test_local_dry_run_does_not_persist(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """dry_run=True の場合は mark_processed を呼んでも状態が保存されないことを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_name="dummy.csv")

    detector1 = LocalDuplicateDetector(config)
    tx = transaction_factory(transaction_id="TX_DRY_RUN")
    detector1.mark_processed(tx)
    detector1.flush()

    assert detector1.is_duplicate(tx) is False

    detector2 = LocalDuplicateDetector(config)
    assert detector2.is_duplicate(tx) is False
    assert (tmp_path / AppConstants.PROCESSED_FILENAME).exists() is False


def test_local_save_writes_valid_json_without_leaving_temp_file(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """保存後に processed.json が有効な JSON であり、一時ファイルが残らないことを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)

    detector.mark_processed(transaction_factory(transaction_id="TX_JSON"))
    detector.flush()

    processed_file = tmp_path / AppConstants.PROCESSED_FILENAME
    stored = json.loads(
        processed_file.read_text(encoding=AppConstants.DEFAULT_TEXT_ENCODING)
    )
    assert stored["transaction_ids"] == ["TX_JSON"]
    assert list(tmp_path.glob("processed.json.tmp")) == []


def test_local_reload_rebuilds_transaction_id_lookup_from_json_list(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """JSON の transaction_ids リストから再読込後の重複判定用 set が再構築されることを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    processed_file = tmp_path / AppConstants.PROCESSED_FILENAME
    processed_file.write_text(
        json.dumps(
            {
                "transaction_ids": ["TX_RELOAD"],
                "fallback_keys": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )

    detector = LocalDuplicateDetector(config)

    assert (
        detector.is_duplicate(transaction_factory(transaction_id="TX_RELOAD")) is True
    )


def test_local_reload_rebuilds_fallback_index_from_json_list(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """JSON の fallback_keys リストから再読込後の補助 index が再構築されることを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    base = datetime(2025, 1, 1, 12, 0, 0)  # noqa: DTZ001
    processed_file = tmp_path / AppConstants.PROCESSED_FILENAME
    processed_file.write_text(
        json.dumps(
            {
                "transaction_ids": [],
                "fallback_keys": [
                    {
                        "datetime": base.isoformat(),
                        "amount": 300,
                        "merchant": "テスト商店",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )

    detector = LocalDuplicateDetector(config)
    duplicate_tx = transaction_factory(
        transaction_id=None,
        amount=300,
        merchant="テスト商店",
        date=base + timedelta(seconds=30),
    )

    assert detector.is_duplicate(duplicate_tx) is True


def test_local_mark_processed_does_not_duplicate_stored_transaction_ids(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """同一 transaction_id を複数回 mark_processed しても保存リストに重複追加しない。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)
    tx = transaction_factory(transaction_id="TX_ONCE")

    detector.mark_processed(tx)
    detector.mark_processed(tx)
    detector.flush()

    stored = json.loads(
        (tmp_path / AppConstants.PROCESSED_FILENAME).read_text(
            encoding=AppConstants.DEFAULT_TEXT_ENCODING,
        )
    )
    assert stored["transaction_ids"] == ["TX_ONCE"]


# フォールバック: tolerance_seconds 内は重複
def test_local_fallback_within_tolerance(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """tolerance_seconds 以内の時刻差を持つ同額取引がフォールバック重複として検知されることを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)

    base = datetime(2025, 1, 1, 12, 0, 0)  # noqa: DTZ001
    tx1 = transaction_factory(transaction_id=None, amount=300, date=base)
    detector.mark_processed(tx1)

    # 30秒後 → tolerance_seconds=60 内なので重複
    tx2 = transaction_factory(
        transaction_id=None,
        amount=300,
        date=base + timedelta(seconds=30),
    )
    assert detector.is_duplicate(tx2) is True


# create_detector が LocalDuplicateDetector を返す
def test_create_detector_local(tmp_path: Path, app_config_factory) -> None:
    """create_detector が backend="local" の場合に LocalDuplicateDetector を返すことを確認する。"""
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = create_detector(config)
    assert isinstance(detector, LocalDuplicateDetector)


def test_create_detector_gcloud_returns_gcloud_detector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    """create_detector が backend="gcloud" の場合に GCloudDuplicateDetector を返すことを確認する。"""
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)

    detector = create_detector(config)

    assert isinstance(detector, GCloudDuplicateDetector)


def test_create_detector_gcloud_raises_when_credentials_path_is_none(
    tmp_path: Path,
    app_config_factory,
) -> None:
    """create_detector は gcloud backend で credentials_path が None の場合に明確な例外を送出する。"""
    config = _build_gcloud_config(tmp_path, app_config_factory)
    config.gcloud_credentials_path = None

    with pytest.raises(
        DuplicateHistoryError,
        match=r'duplicate_detection.backend: "gcloud" の場合は gcloud_credentials_path の指定が必要です。',
    ):
        create_detector(config)


def test_create_detector_gcloud_raises_clear_import_error_when_dependency_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    """google-cloud-firestore 未導入時は案内付き ImportError を送出する。"""
    config = _build_gcloud_config(tmp_path, app_config_factory)
    real_import = __import__

    def _fake_import(
        name,
        globalns=None,
        localns=None,
        fromlist=(),
        level=0,
    ) -> object:
        if name.startswith(("google.cloud", "google.oauth2")):
            msg = f"No module named '{name}'"
            raise ImportError(msg)
        return real_import(name, globalns, localns, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    with pytest.raises(ImportError, match=r"paypay2mf\[gcloud\]"):
        create_detector(config)


def test_create_detector_gcloud_wraps_invalid_credentials_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    """認証情報の読込失敗は DuplicateHistoryError に正規化されることを確認する。"""
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)

    service_account_module = sys.modules["google.oauth2.service_account"]

    class _BrokenCredentials:
        @staticmethod
        def from_service_account_file(_path: str) -> object:
            raise OSError

    monkeypatch.setattr(service_account_module, "Credentials", _BrokenCredentials)

    with pytest.raises(DuplicateHistoryError, match=r"GCloud 認証情報の初期化に失敗"):
        create_detector(config)


def test_gcloud_duplicate_by_transaction_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """transaction_id がある場合は Firestore の document 存在で重複判定する。"""
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)
    detector = create_detector(config)
    client = detector.client
    client.store["TX001"] = {
        "datetime": datetime(2025, 1, 1, 12, 0, 0).isoformat(),  # noqa: DTZ001
        "amount": 100,
        "merchant": "テスト商店",
        "date_bucket": build_date_bucket(datetime(2025, 1, 1, 12, 0, 0)),  # noqa: DTZ001
    }

    assert detector.is_duplicate(transaction_factory(transaction_id="TX001")) is True
    assert detector.is_duplicate(transaction_factory(transaction_id="TX999")) is False


def test_gcloud_duplicate_fallback_within_tolerance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """transaction_id がない場合は amount と merchant の候補から許容幅で重複判定する。"""
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)
    detector = create_detector(config)
    client = detector.client
    base = datetime(2025, 1, 1, 12, 0, 0)  # noqa: DTZ001
    client.store["fallback-1"] = {
        "datetime": base.isoformat(),
        "amount": 300,
        "merchant": "テスト商店",
        "date_bucket": build_date_bucket(base),
    }

    duplicate_tx = transaction_factory(
        transaction_id=None,
        amount=300,
        merchant="テスト商店",
        date=base + timedelta(seconds=30),
    )
    different_tx = transaction_factory(
        transaction_id=None,
        amount=300,
        merchant="別店舗",
        date=base + timedelta(seconds=30),
    )

    assert detector.is_duplicate(duplicate_tx) is True
    assert detector.is_duplicate(different_tx) is False


def test_gcloud_duplicate_fallback_checks_adjacent_date_buckets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """分境界をまたぐ場合は前後の date_bucket も検索対象に含める。"""
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)
    config.duplicate_detection.tolerance_seconds = 30
    detector = create_detector(config)
    client = detector.client
    stored_date = datetime(2025, 1, 1, 12, 0, 10)  # noqa: DTZ001
    client.store["fallback-boundary"] = {
        "datetime": stored_date.isoformat(),
        "amount": 300,
        "merchant": "テスト商店",
        "date_bucket": build_date_bucket(stored_date),
    }

    duplicate_tx = transaction_factory(
        transaction_id=None,
        amount=300,
        merchant="テスト商店",
        date=datetime(2025, 1, 1, 11, 59, 50),  # noqa: DTZ001
    )

    assert detector.is_duplicate(duplicate_tx) is True
    queried_buckets = [
        filters[2][1]
        for filters in client.executed_queries
        if len(filters) == 3 and filters[2][0] == "date_bucket"
    ]
    assert queried_buckets == ["202501011159", "202501011200"]


def test_gcloud_duplicate_fallback_rejects_outside_tolerance_even_with_bucket_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """date_bucket が一致しても tolerance 外なら重複と判定しない。"""
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)
    config.duplicate_detection.tolerance_seconds = 60
    detector = create_detector(config)
    client = detector.client
    stored_date = datetime(2025, 1, 1, 11, 59, 0)  # noqa: DTZ001
    client.store["fallback-outside"] = {
        "datetime": stored_date.isoformat(),
        "amount": 300,
        "merchant": "テスト商店",
        "date_bucket": build_date_bucket(stored_date),
    }

    non_duplicate_tx = transaction_factory(
        transaction_id=None,
        amount=300,
        merchant="テスト商店",
        date=datetime(2025, 1, 1, 12, 0, 1),  # noqa: DTZ001
    )

    assert detector.is_duplicate(non_duplicate_tx) is False


def test_gcloud_duplicate_fallback_raises_explicit_error_for_invalid_datetime_doc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """不正な Firestore datetime を含む候補文書は明示エラーに正規化する。"""
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)
    detector = create_detector(config)
    client = detector.client
    tx = transaction_factory(
        transaction_id=None,
        amount=300,
        merchant="テスト商店",
        date=datetime(2025, 1, 1, 12, 0, 0),  # noqa: DTZ001
    )
    client.store["bad-doc"] = {
        "datetime": "not-a-datetime",
        "amount": 300,
        "merchant": "テスト商店",
        "date_bucket": build_date_bucket(tx.date),
    }

    with pytest.raises(DuplicateHistoryError, match=r"paypay_transactions/bad-doc"):
        detector.is_duplicate(tx)


def test_gcloud_mark_processed_writes_expected_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """mark_processed は transaction_id または fallback key を doc_id に使って保存する。"""
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)
    detector = create_detector(config)
    client = detector.client
    transaction = transaction_factory(transaction_id="TX_SAVE", amount=920)

    detector.mark_processed(transaction)

    assert client.store == {
        "TX_SAVE": {
            "datetime": transaction.date.isoformat(),
            "amount": 920,
            "merchant": transaction.merchant,
            "date_bucket": build_date_bucket(transaction.date),
        }
    }


def test_gcloud_mark_processed_without_transaction_id_writes_date_bucket_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """transaction_id がない場合も date_bucket を含む payload で保存する。"""
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)
    detector = create_detector(config)
    client = detector.client
    transaction = transaction_factory(
        transaction_id=None,
        amount=920,
        merchant="テスト商店",
        date=datetime(2025, 1, 1, 12, 34, 56),  # noqa: DTZ001
    )

    detector.mark_processed(transaction)

    assert client.store == {
        build_firestore_fallback_doc_id(transaction): {
            "datetime": transaction.date.isoformat(),
            "amount": 920,
            "merchant": transaction.merchant,
            "date_bucket": "202501011234",
        }
    }


def test_gcloud_fallback_doc_id_is_safe_when_merchant_contains_slash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """fallback document id が merchant の記号に依存しない安全な値になることを確認する。"""
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)
    detector = create_detector(config)
    client = detector.client
    transaction = transaction_factory(
        transaction_id=None,
        amount=920,
        merchant="A/B 店舗",
        date=datetime(2025, 1, 1, 12, 34, 56),  # noqa: DTZ001
    )

    detector.mark_processed(transaction)

    stored_doc_ids = list(client.store)
    assert stored_doc_ids == [build_firestore_fallback_doc_id(transaction)]
    assert "/" not in stored_doc_ids[0]


def test_gcloud_mark_processed_skips_write_in_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """dry_run=True の場合は Firestore に書き込まない。"""
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory, dry_run=True)
    detector = create_detector(config)
    client = detector.client

    detector.mark_processed(transaction_factory(transaction_id="TX_SKIP"))

    assert client.store == {}
