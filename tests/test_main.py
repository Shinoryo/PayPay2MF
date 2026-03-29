"""main モジュールのテスト。"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

import main as app_main
from src.models import AppConfig, LogSettings, ParseFailure, Transaction

if TYPE_CHECKING:
    from pathlib import Path


class _FakeDetector:
    def __init__(self, duplicate_results: list[bool] | None = None) -> None:
        self._duplicate_results = list(duplicate_results or [])
        self.mark_processed = Mock()

    def is_duplicate(self, _tx: Transaction) -> bool:
        if not self._duplicate_results:
            return False
        return self._duplicate_results.pop(0)


class _FakeRegistrar:
    def __init__(self, failures: set[str] | None = None) -> None:
        self._failures = failures or set()
        self.registered: list[str] = []

    def register(self, tx: Transaction) -> None:
        self.registered.append(tx.transaction_id or tx.merchant)
        if (tx.transaction_id or "") in self._failures:
            msg = f"failed: {tx.transaction_id}"
            raise RuntimeError(msg)


def _make_config(tmp_path: Path, *, dry_run: bool = True) -> AppConfig:
    csv_file = tmp_path / "input.csv"
    csv_file.write_text("header\n", encoding="utf-8")
    return AppConfig(
        chrome_user_data_dir="C:\\dummy",
        chrome_profile="Default",
        dry_run=dry_run,
        input_csv=csv_file,
        mf_account="PayPay残高",
        log_settings=LogSettings(logs_dir=tmp_path),
    )


def _make_tx(transaction_id: str) -> Transaction:
    return Transaction(
        date=datetime(2025, 1, 1, 12, 0, 0),  # noqa: DTZ001
        amount=100,
        direction="out",
        memo="支払い",
        merchant=f"merchant-{transaction_id}",
        transaction_id=transaction_id,
    )


def test_build_transactions_reports_parse_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """解析失敗 CSV 出力と重複除外を含む取引準備結果を確認する。"""
    config = _make_config(tmp_path)
    logger = Mock(spec=logging.Logger)
    detector = _FakeDetector([False, True])
    parse_failures = [
        ParseFailure(
            row_index=3,
            transaction_id="TX999",
            merchant="broken",
            error_type="parse_error",
            error_message="bad row",
            raw_row={"取引先": "broken"},
        ),
    ]

    parse_csv_mock = Mock(
        return_value=([_make_tx("TX001"), _make_tx("TX002")], parse_failures),
    )
    monkeypatch.setattr(app_main, "parse_csv", parse_csv_mock)
    monkeypatch.setattr(app_main, "create_detector", Mock(return_value=detector))
    parse_error_csv = tmp_path / "parse_error.csv"
    write_parse_error_csv_mock = Mock(
        return_value=parse_error_csv,
    )
    monkeypatch.setattr(
        app_main,
        "write_parse_error_csv",
        write_parse_error_csv_mock,
    )

    prepared = app_main.build_transactions(config, logger)

    assert prepared.to_process == [_make_tx("TX001")]
    assert prepared.excluded_count == 0
    assert prepared.skip_count == 1
    write_parse_error_csv_mock.assert_called_once_with(parse_failures, config)
    logger.warning.assert_any_call("CSV 解析失敗: %d件", 1)
    logger.info.assert_any_call("重複スキップ: %d件", 1)


def test_run_dry_run_logs_completion() -> None:
    """dry_run 用 helper が終了ログを出すことを確認する。"""
    logger = Mock(spec=logging.Logger)

    app_main.run_dry_run(logger, 2)

    logger.info.assert_any_call("ドライラン完了: 登録対象 %d件", 2)
    logger.info.assert_any_call("アプリケーションを終了します")


def test_run_registration_continues_after_item_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """個別登録失敗時も残りの取引を継続処理することを確認する。"""
    config = _make_config(tmp_path, dry_run=False)
    logger = Mock(spec=logging.Logger)
    detector = _FakeDetector()
    registrar = _FakeRegistrar({"TX002"})
    registrar_factory = Mock(return_value=nullcontext(registrar))
    monkeypatch.setattr(app_main, "MFRegistrar", registrar_factory)

    result = app_main.run_registration(
        config,
        logger,
        detector,
        [_make_tx("TX001"), _make_tx("TX002")],
    )

    assert result.success_count == 1
    assert result.failed_records == ["failed: TX002"]
    assert detector.mark_processed.call_count == 1
    detector.mark_processed.assert_called_once()
    logger.exception.assert_called_once()
    registrar_factory.assert_called_once_with(config, logger)


def test_main_exits_when_config_load_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """設定読み込み失敗時にエラーメッセージを出して終了することを確認する。"""
    monkeypatch.setattr(
        app_main,
        "load_config",
        Mock(side_effect=ValueError("bad config")),
    )
    monkeypatch.setattr(app_main, "setup_logger", Mock())

    with pytest.raises(SystemExit) as exc_info:
        app_main.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "設定ファイルの読み込みに失敗しました" in captured.out
    assert "bad config" in captured.out


def test_main_dry_run_skips_browser_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dry_run では Chrome 確認と登録処理を呼ばないことを確認する。"""
    config = _make_config(tmp_path, dry_run=True)
    logger = Mock(spec=logging.Logger)

    monkeypatch.setattr(app_main, "load_config", Mock(return_value=config))
    monkeypatch.setattr(app_main, "setup_logger", Mock(return_value=logger))
    ensure_mock = Mock()
    monkeypatch.setattr(app_main, "ensure_chrome_stopped", ensure_mock)
    build_mock = Mock(
        return_value=app_main.PreparedTransactions(
            detector=_FakeDetector(),
            to_process=[_make_tx("TX001")],
            excluded_count=0,
            skip_count=0,
        ),
    )
    monkeypatch.setattr(app_main, "build_transactions", build_mock)
    run_dry_run_mock = Mock()
    monkeypatch.setattr(app_main, "run_dry_run", run_dry_run_mock)
    run_registration_mock = Mock()
    monkeypatch.setattr(app_main, "run_registration", run_registration_mock)

    app_main.main()

    ensure_mock.assert_called_once_with(config, logger)
    build_mock.assert_called_once_with(config, logger)
    run_dry_run_mock.assert_called_once_with(logger, 1)
    run_registration_mock.assert_not_called()
