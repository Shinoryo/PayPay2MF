"""firestore_backfill モジュールのテスト。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from paypay2mf import firestore_backfill
from paypay2mf.constants import AppConstants
from paypay2mf.duplicate_detector import build_date_bucket
from tests.test_duplicate_detector import (
    _FakeFirestoreClient,
    _install_fake_gcloud_modules,
)


class _FakeBackfillDetector:
    def __init__(self, store: dict[str, dict]) -> None:
        self.client = _FakeFirestoreClient(credentials=("creds", "dummy"))
        self.client.store.update({doc_id: dict(data) for doc_id, data in store.items()})
        self.batch_call_count = 0

    def collection(self) -> object:
        return self.client.collection("paypay_transactions")

    def batch(self) -> object:
        self.batch_call_count += 1
        return self.client.batch()


def _build_datetime(minutes: int) -> datetime:
    return datetime(2025, 3, 28, 12, 0, 30, tzinfo=UTC) + timedelta(minutes=minutes)


@pytest.fixture
def summary() -> firestore_backfill.BackfillSummary:
    """共通の backfill 集計結果を返す。"""
    return firestore_backfill.BackfillSummary(
        scanned_count=3,
        updated_count=2,
        skipped_count=1,
    )


def test_parse_args_accepts_dry_run_limit_and_config() -> None:
    """既存オプションと --config が引き続き受理されることを確認する。"""
    config_path = Path("custom.yml")

    args = firestore_backfill.parse_args(
        ["--dry-run", "--limit", "10", "--config", str(config_path)]
    )

    assert args.dry_run is True
    assert args.limit == 10
    assert args.config == config_path


def test_parse_args_rejects_negative_limit() -> None:
    """--limit は負数を受け付けない。"""
    with pytest.raises(SystemExit):
        firestore_backfill.parse_args(["--limit", "-1"])


def test_backfill_skips_invalid_datetime_and_logs_warning() -> None:
    """不正 datetime は skip し、警告だけを残すことを確認する。"""
    valid_datetime = _build_datetime(0)
    detector = _FakeBackfillDetector(
        {
            "blank": {"datetime": ""},
            "whitespace": {"datetime": "   "},
            "bad-format": {"datetime": "not-a-datetime"},
            "valid": {"datetime": valid_datetime.isoformat()},
        }
    )
    logger = Mock(spec=logging.Logger)

    summary = firestore_backfill.backfill_date_buckets(
        detector,
        logger,
        dry_run=False,
        limit=None,
    )

    assert summary == firestore_backfill.BackfillSummary(
        scanned_count=4,
        updated_count=1,
        skipped_count=3,
    )
    assert [len(commit) for commit in detector.client.batch_commits] == [1]
    assert detector.client.store["valid"]["date_bucket"] == build_date_bucket(
        valid_datetime
    )
    assert [call.args[1] for call in logger.warning.call_args_list] == [
        "blank",
        "whitespace",
        "bad-format",
    ]


def test_backfill_commits_every_500_writes_and_tail_commit() -> None:
    """更新対象が 500 件を超えると閾値 commit と tail commit が走ることを確認する。"""
    store = {
        f"doc-{index:03d}": {"datetime": _build_datetime(index).isoformat()}
        for index in range(501)
    }
    detector = _FakeBackfillDetector(store)
    logger = Mock(spec=logging.Logger)

    summary = firestore_backfill.backfill_date_buckets(
        detector,
        logger,
        dry_run=False,
        limit=None,
    )

    assert summary == firestore_backfill.BackfillSummary(
        scanned_count=501,
        updated_count=501,
        skipped_count=0,
    )
    assert detector.batch_call_count == 2
    assert [len(commit) for commit in detector.client.batch_commits] == [500, 1]
    first_operation = detector.client.batch_commits[0][0]
    last_operation = detector.client.batch_commits[-1][0]
    assert first_operation == {
        "doc_id": "doc-000",
        "data": {"date_bucket": build_date_bucket(_build_datetime(0))},
        "merge": True,
    }
    assert last_operation == {
        "doc_id": "doc-500",
        "data": {"date_bucket": build_date_bucket(_build_datetime(500))},
        "merge": True,
    }


def test_backfill_commits_remaining_writes_at_end() -> None:
    """閾値未満でもループ終了時に残件 commit されることを確認する。"""
    detector = _FakeBackfillDetector(
        {
            "doc-a": {"datetime": _build_datetime(1).isoformat()},
            "doc-b": {"datetime": _build_datetime(2).isoformat()},
        }
    )
    logger = Mock(spec=logging.Logger)

    summary = firestore_backfill.backfill_date_buckets(
        detector,
        logger,
        dry_run=False,
        limit=None,
    )

    assert summary == firestore_backfill.BackfillSummary(
        scanned_count=2,
        updated_count=2,
        skipped_count=0,
    )
    assert detector.batch_call_count == 1
    assert [len(commit) for commit in detector.client.batch_commits] == [2]


def test_backfill_dry_run_counts_updates_without_writing() -> None:
    """dry-run では更新件数だけ数え、Firestore へ書き込まないことを確認する。"""
    original_store = {
        "doc-a": {"datetime": _build_datetime(0).isoformat()},
        "doc-b": {"datetime": _build_datetime(1).isoformat(), "date_bucket": "stale"},
        "doc-c": {"datetime": "invalid"},
    }
    detector = _FakeBackfillDetector(original_store)
    logger = Mock(spec=logging.Logger)

    summary = firestore_backfill.backfill_date_buckets(
        detector,
        logger,
        dry_run=True,
        limit=None,
    )

    assert summary == firestore_backfill.BackfillSummary(
        scanned_count=3,
        updated_count=2,
        skipped_count=1,
    )
    assert detector.batch_call_count == 0
    assert detector.client.batch_commits == []
    assert detector.client.store == original_store


def test_backfill_counts_current_date_bucket_as_skipped() -> None:
    """既に最新の date_bucket を持つ文書も skipped_count に含める。"""
    current_datetime = _build_datetime(0)
    detector = _FakeBackfillDetector(
        {
            "current": {
                "datetime": current_datetime.isoformat(),
                "date_bucket": build_date_bucket(current_datetime),
            },
        }
    )
    logger = Mock(spec=logging.Logger)

    summary = firestore_backfill.backfill_date_buckets(
        detector,
        logger,
        dry_run=True,
        limit=None,
    )

    assert summary == firestore_backfill.BackfillSummary(
        scanned_count=1,
        updated_count=0,
        skipped_count=1,
    )


def test_load_gcloud_detector_accepts_minimal_backfill_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """backfill は通常アプリの必須5項目なしでも最小 gcloud 設定で初期化できる。"""
    _install_fake_gcloud_modules(monkeypatch)
    credentials_file = tmp_path / "service-account.json"
    credentials_file.write_text("{}", encoding=AppConstants.DEFAULT_TEXT_ENCODING)
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        (
            "duplicate_detection:\n"
            "  backend: 'gcloud'\n"
            "  tolerance_seconds: 60\n"
            "gcloud_credentials_path: 'service-account.json'"
        ),
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )
    logger = Mock(spec=logging.Logger)
    captured_detectors: list[object] = []

    def _capture_backfill(
        detector: object,
        logger: object,
        *,
        dry_run: bool,
        limit: int | None,
    ) -> firestore_backfill.BackfillSummary:
        _ = (logger, dry_run, limit)
        captured_detectors.append(detector)
        return firestore_backfill.BackfillSummary(0, 0, 0)

    monkeypatch.setattr(
        firestore_backfill,
        "backfill_date_buckets",
        _capture_backfill,
    )
    monkeypatch.setattr(firestore_backfill.logging, "basicConfig", Mock())
    monkeypatch.setattr(
        firestore_backfill.logging,
        "getLogger",
        Mock(return_value=logger),
    )

    firestore_backfill.main(["--config", str(config_path), "--dry-run"])

    assert len(captured_detectors) == 1
    detector = captured_detectors[0]
    assert detector.client.credentials == ("creds", str(credentials_file))


def test_load_backfill_config_rejects_credentials_directory(tmp_path: Path) -> None:
    """backfill 設定の gcloud_credentials_path にディレクトリを指定した場合は ValueError になる。"""
    credentials_dir = tmp_path / "service-account.json"
    credentials_dir.mkdir()
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        (
            "duplicate_detection:\n"
            "  backend: 'gcloud'\n"
            "  tolerance_seconds: 60\n"
            "gcloud_credentials_path: 'service-account.json'"
        ),
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )
    load_backfill_config = firestore_backfill._load_backfill_config  # noqa: SLF001

    with pytest.raises(
        ValueError,
        match=r"gcloud_credentials_path にはファイルを指定してください",
    ):
        load_backfill_config(config_path)


def test_main_uses_cli_config_path_before_env_and_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    summary: firestore_backfill.BackfillSummary,
) -> None:
    """--config 指定が他の探索経路より優先されることを確認する。"""
    logger = Mock(spec=logging.Logger)
    cli_config = tmp_path / "cli.yml"
    env_config = tmp_path / "env.yml"
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    (cwd_dir / "config.yml").write_text("", encoding=AppConstants.DEFAULT_TEXT_ENCODING)

    monkeypatch.chdir(cwd_dir)
    monkeypatch.setenv("PAYPAY2MF_CONFIG", str(env_config))
    monkeypatch.setattr(firestore_backfill.logging, "basicConfig", Mock())
    monkeypatch.setattr(
        firestore_backfill.logging, "getLogger", Mock(return_value=logger)
    )
    load_gcloud_detector_mock = Mock(return_value=object())
    monkeypatch.setattr(
        firestore_backfill,
        "_load_gcloud_detector",
        load_gcloud_detector_mock,
    )
    monkeypatch.setattr(
        firestore_backfill,
        "backfill_date_buckets",
        Mock(return_value=summary),
    )

    firestore_backfill.main(["--config", str(cli_config)])

    load_gcloud_detector_mock.assert_called_once_with(cli_config)


def test_main_uses_env_config_path_when_cli_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    summary: firestore_backfill.BackfillSummary,
) -> None:
    """CLI 未指定時は PAYPAY2MF_CONFIG を優先することを確認する。"""
    logger = Mock(spec=logging.Logger)
    env_config = tmp_path / "env.yml"
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    (cwd_dir / "config.yml").write_text("", encoding=AppConstants.DEFAULT_TEXT_ENCODING)

    monkeypatch.chdir(cwd_dir)
    monkeypatch.setenv("PAYPAY2MF_CONFIG", str(env_config))
    monkeypatch.setattr(firestore_backfill.logging, "basicConfig", Mock())
    monkeypatch.setattr(
        firestore_backfill.logging, "getLogger", Mock(return_value=logger)
    )
    load_gcloud_detector_mock = Mock(return_value=object())
    monkeypatch.setattr(
        firestore_backfill,
        "_load_gcloud_detector",
        load_gcloud_detector_mock,
    )
    monkeypatch.setattr(
        firestore_backfill,
        "backfill_date_buckets",
        Mock(return_value=summary),
    )

    firestore_backfill.main([])

    load_gcloud_detector_mock.assert_called_once_with(env_config)


def test_main_uses_cwd_config_path_when_cli_and_env_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    summary: firestore_backfill.BackfillSummary,
) -> None:
    """CLI と環境変数が未指定なら cwd の config.yml を使うことを確認する。"""
    logger = Mock(spec=logging.Logger)
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    cwd_config = cwd_dir / "config.yml"
    cwd_config.write_text("", encoding=AppConstants.DEFAULT_TEXT_ENCODING)

    monkeypatch.chdir(cwd_dir)
    monkeypatch.delenv("PAYPAY2MF_CONFIG", raising=False)
    monkeypatch.setattr(firestore_backfill.logging, "basicConfig", Mock())
    monkeypatch.setattr(
        firestore_backfill.logging, "getLogger", Mock(return_value=logger)
    )
    load_gcloud_detector_mock = Mock(return_value=object())
    monkeypatch.setattr(
        firestore_backfill,
        "_load_gcloud_detector",
        load_gcloud_detector_mock,
    )
    monkeypatch.setattr(
        firestore_backfill,
        "backfill_date_buckets",
        Mock(return_value=summary),
    )

    firestore_backfill.main([])

    load_gcloud_detector_mock.assert_called_once_with(cwd_config)


def test_main_falls_back_to_module_config_path_when_cwd_config_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    summary: firestore_backfill.BackfillSummary,
) -> None:
    """cwd に config.yml が無い場合はモジュール同居へフォールバックすることを確認する。"""
    logger = Mock(spec=logging.Logger)
    cwd_dir = tmp_path / "cwd"
    module_dir = tmp_path / "module"
    cwd_dir.mkdir()
    module_dir.mkdir()
    module_config = module_dir / "config.yml"
    module_config.write_text("", encoding=AppConstants.DEFAULT_TEXT_ENCODING)

    monkeypatch.chdir(cwd_dir)
    monkeypatch.delenv("PAYPAY2MF_CONFIG", raising=False)
    monkeypatch.setattr(
        firestore_backfill, "__file__", str(module_dir / "firestore_backfill.py")
    )
    monkeypatch.setattr(firestore_backfill.logging, "basicConfig", Mock())
    monkeypatch.setattr(
        firestore_backfill.logging, "getLogger", Mock(return_value=logger)
    )
    load_gcloud_detector_mock = Mock(return_value=object())
    monkeypatch.setattr(
        firestore_backfill,
        "_load_gcloud_detector",
        load_gcloud_detector_mock,
    )
    monkeypatch.setattr(
        firestore_backfill,
        "backfill_date_buckets",
        Mock(return_value=summary),
    )

    firestore_backfill.main([])

    load_gcloud_detector_mock.assert_called_once_with(module_config)
