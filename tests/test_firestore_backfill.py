"""firestore_backfill モジュールのテスト。"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import Mock

import pytest

import firestore_backfill
from src.constants import AppConstants


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
    monkeypatch.setattr(firestore_backfill.logging, "getLogger", Mock(return_value=logger))
    monkeypatch.setattr(
        firestore_backfill,
        "_load_gcloud_detector",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(
        firestore_backfill,
        "backfill_date_buckets",
        Mock(return_value=summary),
    )

    firestore_backfill.main(["--config", str(cli_config)])

    firestore_backfill._load_gcloud_detector.assert_called_once_with(cli_config)


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
    monkeypatch.setattr(firestore_backfill.logging, "getLogger", Mock(return_value=logger))
    monkeypatch.setattr(
        firestore_backfill,
        "_load_gcloud_detector",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(
        firestore_backfill,
        "backfill_date_buckets",
        Mock(return_value=summary),
    )

    firestore_backfill.main([])

    firestore_backfill._load_gcloud_detector.assert_called_once_with(env_config)


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
    monkeypatch.setattr(firestore_backfill.logging, "getLogger", Mock(return_value=logger))
    monkeypatch.setattr(
        firestore_backfill,
        "_load_gcloud_detector",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(
        firestore_backfill,
        "backfill_date_buckets",
        Mock(return_value=summary),
    )

    firestore_backfill.main([])

    firestore_backfill._load_gcloud_detector.assert_called_once_with(cwd_config)


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
    monkeypatch.setattr(firestore_backfill, "__file__", str(module_dir / "firestore_backfill.py"))
    monkeypatch.setattr(firestore_backfill.logging, "basicConfig", Mock())
    monkeypatch.setattr(firestore_backfill.logging, "getLogger", Mock(return_value=logger))
    monkeypatch.setattr(
        firestore_backfill,
        "_load_gcloud_detector",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(
        firestore_backfill,
        "backfill_date_buckets",
        Mock(return_value=summary),
    )

    firestore_backfill.main([])

    firestore_backfill._load_gcloud_detector.assert_called_once_with(module_config)
