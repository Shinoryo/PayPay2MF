"""duplicate_detector モジュールのテスト。"""

from __future__ import annotations

import builtins
import json
import sys
import types
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from paypay2mf.constants import AppConstants
from paypay2mf.duplicate_detector import (
    DuplicateHistoryError,
    GCloudDuplicateDetector,
    LocalDuplicateDetector,
    create_detector,
    resolve_row_fingerprint,
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

    @property
    def doc_id(self) -> str:
        return self._doc_id


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
    def __init__(self, store: dict[str, dict]) -> None:
        self._store = store

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


class _FakeFirestoreClient:
    def __init__(
        self,
        *,
        credentials: object,
        database: str = AppConstants.DEFAULT_FIRESTORE_DATABASE_ID,
    ) -> None:
        self.credentials = credentials
        self.database = database
        self.store: dict[str, dict] = {}
        self.batch_commits: list[list[dict[str, object]]] = []

    def collection(self, _name: str) -> _FakeFirestoreCollection:
        return _FakeFirestoreCollection(self.store)

    def batch(self) -> object:
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
    database_id: str = AppConstants.DEFAULT_FIRESTORE_DATABASE_ID,
) -> AppConfig:
    config = app_config_factory(tmp_path, dry_run=dry_run, input_csv_name="dummy.csv")
    credentials_file = tmp_path / "service-account.json"
    credentials_file.write_text("{}", encoding=AppConstants.DEFAULT_TEXT_ENCODING)
    config.duplicate_detection.backend = AppConstants.BACKEND_GCLOUD
    config.duplicate_detection.database_id = database_id
    config.gcloud_credentials_path = credentials_file
    return config


def test_resolve_row_fingerprint_prefers_precomputed_value(transaction_factory) -> None:
    tx = transaction_factory(row_fingerprint="fp-precomputed")
    assert resolve_row_fingerprint(tx) == "fp-precomputed"


def test_resolve_row_fingerprint_builds_when_missing(transaction_factory) -> None:
    tx = transaction_factory(
        row_fingerprint=AppConstants.EMPTY_STRING, transaction_id="TX001"
    )
    result = resolve_row_fingerprint(tx)
    assert result
    assert result != "TX001"


def test_local_duplicate_by_row_fingerprint(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)
    tx = transaction_factory(row_fingerprint="fp-001")

    assert detector.is_duplicate(tx) is False
    detector.mark_processed(tx)
    assert detector.is_duplicate(tx) is True


def test_local_non_duplicate_when_fingerprint_differs(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = LocalDuplicateDetector(config)
    tx1 = transaction_factory(row_fingerprint="fp-a")
    tx2 = transaction_factory(row_fingerprint="fp-b", transaction_id="TX002")

    detector.mark_processed(tx1)
    assert detector.is_duplicate(tx2) is False


def test_local_persistence_uses_row_fingerprints(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")

    detector1 = LocalDuplicateDetector(config)
    tx = transaction_factory(row_fingerprint="fp-persist")
    detector1.mark_processed(tx)
    detector1.flush()

    detector2 = LocalDuplicateDetector(config)
    assert detector2.is_duplicate(tx) is True

    stored = json.loads(
        (tmp_path / AppConstants.PROCESSED_FILENAME).read_text(
            encoding=AppConstants.DEFAULT_TEXT_ENCODING
        )
    )
    assert stored["row_fingerprints"] == ["fp-persist"]


def test_local_corrupted_history_is_backed_up_and_raises_explicit_error(
    tmp_path: Path,
    app_config_factory,
) -> None:
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    processed_file = tmp_path / AppConstants.PROCESSED_FILENAME
    processed_file.write_text(
        "{broken json}",
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )

    with pytest.raises(DuplicateHistoryError, match=r"processed\.json"):
        LocalDuplicateDetector(config)

    backup_files = list(tmp_path.glob("processed.corrupted_*.json"))
    assert len(backup_files) == 1
    assert processed_file.exists() is False


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"row_fingerprints": {}},
        {"row_fingerprints": [123]},
    ],
)
def test_local_invalid_schema_is_backed_up_and_raises(
    tmp_path: Path,
    app_config_factory,
    payload: object,
) -> None:
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


def test_local_dry_run_does_not_persist(
    tmp_path: Path,
    app_config_factory,
    transaction_factory,
) -> None:
    config = app_config_factory(tmp_path, dry_run=True, input_csv_name="dummy.csv")

    detector1 = LocalDuplicateDetector(config)
    tx = transaction_factory(row_fingerprint="fp-dry")
    detector1.mark_processed(tx)
    detector1.flush()

    assert detector1.is_duplicate(tx) is False
    detector2 = LocalDuplicateDetector(config)
    assert detector2.is_duplicate(tx) is False
    assert (tmp_path / AppConstants.PROCESSED_FILENAME).exists() is False


def test_create_detector_local(tmp_path: Path, app_config_factory) -> None:
    config = app_config_factory(tmp_path, input_csv_name="dummy.csv")
    detector = create_detector(config)
    assert isinstance(detector, LocalDuplicateDetector)


def test_create_detector_gcloud_returns_gcloud_detector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)

    detector = create_detector(config)

    assert isinstance(detector, GCloudDuplicateDetector)
    assert detector.client.database == AppConstants.DEFAULT_FIRESTORE_DATABASE_ID


def test_gcloud_detector_propagates_custom_database_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(
        tmp_path, app_config_factory, database_id="custom-db-instance"
    )

    detector = create_detector(config)

    assert isinstance(detector, GCloudDuplicateDetector)
    assert detector.client.database == "custom-db-instance"


def test_create_detector_gcloud_raises_when_credentials_path_is_none(
    tmp_path: Path,
    app_config_factory,
) -> None:
    config = _build_gcloud_config(tmp_path, app_config_factory)
    config.gcloud_credentials_path = None

    with pytest.raises(
        DuplicateHistoryError,
        match=r'duplicate_detection.backend: "gcloud" の場合は gcloud_credentials_path の指定が必要です。',
    ):
        create_detector(config)


def test_create_detector_gcloud_shows_dependency_install_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    config = _build_gcloud_config(tmp_path, app_config_factory)

    monkeypatch.delitem(sys.modules, "google.cloud", raising=False)
    monkeypatch.delitem(sys.modules, "google.cloud.firestore", raising=False)
    monkeypatch.delitem(sys.modules, "google.oauth2", raising=False)
    monkeypatch.delitem(sys.modules, "google.oauth2.service_account", raising=False)
    original_import = builtins.__import__

    def _raise_for_google(
        name: str,
        global_vars: dict | None = None,
        local_vars: dict | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        _ = (global_vars, local_vars, fromlist, level)
        if name.startswith(("google.cloud", "google.oauth2")):
            msg = "missing google modules"
            raise ImportError(msg)
        return original_import(name, global_vars, local_vars, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raise_for_google)

    with pytest.raises(
        ImportError,
        match=r"google-cloud-firestore がインストールされていません。",
    ):
        create_detector(config)


def test_create_detector_gcloud_normalizes_credentials_load_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)

    service_account_module = sys.modules["google.oauth2.service_account"]
    credentials_class = service_account_module.Credentials

    def _raise_credentials_error(_path: str) -> tuple[str, str]:
        msg = "invalid credentials"
        raise ValueError(msg)

    monkeypatch.setattr(
        credentials_class,
        "from_service_account_file",
        staticmethod(_raise_credentials_error),
    )

    with pytest.raises(
        DuplicateHistoryError,
        match=r"GCloud 認証情報の初期化に失敗しました",
    ):
        create_detector(config)


def test_gcloud_duplicate_by_row_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)
    detector = create_detector(config)
    client = detector.client
    tx = transaction_factory(row_fingerprint="fp-gcloud")

    assert detector.is_duplicate(tx) is False

    detector.mark_processed(tx)

    assert detector.is_duplicate(tx) is True
    assert "fp-gcloud" in client.store


def test_gcloud_mark_processed_skips_write_in_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory, dry_run=True)
    detector = create_detector(config)
    client = detector.client

    detector.mark_processed(transaction_factory(row_fingerprint="fp-skip"))

    assert client.store == {}


def test_gcloud_payload_contains_audit_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    _install_fake_gcloud_modules(monkeypatch)
    config = _build_gcloud_config(tmp_path, app_config_factory)
    detector = create_detector(config)
    client = detector.client
    tx = transaction_factory(
        row_fingerprint="fp-audit",
        transaction_id="TX-AUDIT",
        amount=920,
        merchant="テスト商店",
        date=datetime(2025, 1, 1, 12, 34, 56),  # noqa: DTZ001
    )

    detector.mark_processed(tx)

    assert client.store["fp-audit"]["row_fingerprint"] == "fp-audit"
    assert client.store["fp-audit"]["amount"] == 920
    assert client.store["fp-audit"]["merchant"] == "テスト商店"
    assert client.store["fp-audit"]["transaction_id"] == "TX-AUDIT"
