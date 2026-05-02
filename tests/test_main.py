"""main モジュールのテスト。

対応テストレイヤー:
    integration_flow: main フローのオーケストレーション、終了経路、副作用

対応テストケース:
    TC-05-01: ドライラン実行
    TC-05-02: ドライランのログ出力と重複履歴保護
    TC-09-01: 解析失敗 CSV への分離と正常行継続
    TC-09-03: 登録失敗時の継続処理と終了経路
"""

from __future__ import annotations

import csv
import logging
from contextlib import nullcontext
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

import paypay2mf.cli as app_main
from paypay2mf.constants import AppConstants
from paypay2mf.duplicate_detector import (
    DuplicateHistoryError,
    DuplicateHistorySaveError,
    LocalDuplicateDetector,
)

pytestmark = pytest.mark.integration_flow

_MSG_PARSE_FAILURE_COUNT = "CSV 解析失敗: %d件"
_MSG_DUPLICATE_SKIP_COUNT = "重複スキップ: %d件"
_MSG_CSV_READ_FAILED = "CSV 読み込みに失敗しました"
_MSG_DRY_RUN_COMPLETE = "ドライラン完了: 登録対象 %d件"
_MSG_APP_EXIT = "アプリケーションを終了します"
_MSG_REGISTRATION_BOOT_FAILED = "Chrome の起動またはMFへの遷移に失敗しました"
_MSG_CONTEXT_EXIT_FAILED = "context exit failed"
_MSG_DUPLICATE_HISTORY_SAVE_FAILED = "重複履歴ファイルの保存に失敗しました: %s"
_MSG_DUPLICATE_HISTORY_UPDATE_FAILED = "重複履歴の更新に失敗しました: %s"
_MSG_DUPLICATE_BACKEND_INIT_FAILED = "重複検知バックエンドの初期化に失敗しました: %s"

if TYPE_CHECKING:
    from pathlib import Path

    from paypay2mf.models import Transaction


class _FakeDetector:
    def __init__(
        self,
        duplicate_results: list[bool] | None = None,
        *,
        flush_side_effect: Exception | None = None,
    ) -> None:
        self._duplicate_results = list(duplicate_results or [])
        self.mark_processed = Mock()
        self.flush = Mock(side_effect=flush_side_effect)

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


def test_build_transactions_reports_parse_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    parse_failure_factory,
    transaction_factory,
) -> None:
    """TC-09-01: 解析失敗を記録しつつ重複除外後の処理対象を返すことを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    detector = _FakeDetector([False, True])
    parse_failures = [
        parse_failure_factory(
            transaction_id="TX999",
            merchant="broken",
            raw_row={"取引先": "broken"},
        ),
    ]
    first_tx = transaction_factory(transaction_id="TX001", merchant="merchant-TX001")
    second_tx = transaction_factory(transaction_id="TX002", merchant="merchant-TX002")

    parse_csv_mock = Mock(return_value=([first_tx, second_tx], parse_failures))
    monkeypatch.setattr(app_main, "parse_csv", parse_csv_mock)
    monkeypatch.setattr(app_main, "create_detector", Mock(return_value=detector))
    parse_error_csv = tmp_path / "parse_error.csv"
    write_parse_error_csv_mock = Mock(return_value=parse_error_csv)
    monkeypatch.setattr(
        app_main,
        "write_parse_error_csv",
        write_parse_error_csv_mock,
    )

    prepared = app_main.build_transactions(config, logger)

    assert prepared.to_process == [first_tx]
    assert prepared.excluded_count == 0
    assert prepared.skip_count == 1
    write_parse_error_csv_mock.assert_called_once_with(parse_failures, config)
    logger.warning.assert_any_call(_MSG_PARSE_FAILURE_COUNT, 1)
    logger.info.assert_any_call(_MSG_DUPLICATE_SKIP_COUNT, 1)


def test_build_transactions_writes_parse_error_csv_and_keeps_valid_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    parse_failure_factory,
    transaction_factory,
) -> None:
    """TC-09-01: 解析失敗 CSV を実出力しつつ正常行を継続処理できることを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    valid_tx = transaction_factory(transaction_id="TX001", merchant="merchant-TX001")
    parse_failures = [
        parse_failure_factory(
            transaction_id="TX999",
            merchant="broken",
            error_type="invalid_date",
            raw_row={"取引先": "broken"},
        ),
    ]

    monkeypatch.setattr(
        app_main,
        "parse_csv",
        Mock(return_value=([valid_tx], parse_failures)),
    )

    prepared = app_main.build_transactions(config, logger)

    assert prepared.to_process == [valid_tx]

    parse_error_files = list(tmp_path.glob("parse_error_*.csv"))
    assert len(parse_error_files) == 1

    with parse_error_files[0].open(
        encoding=AppConstants.ENCODING_UTF8_SIG,
        newline=AppConstants.EMPTY_STRING,
    ) as file_obj:
        rows = list(csv.DictReader(file_obj))

    assert rows == [
        {
            "row_index": "3",
            "error_type": "invalid_date",
            "error_message": "bad row",
        },
    ]
    logger.warning.assert_any_call(_MSG_PARSE_FAILURE_COUNT, 1)


def test_build_transactions_exits_when_parse_csv_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    """TC-09-01: 想定内の CSV 読み込み失敗は終了することを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)

    monkeypatch.setattr(
        app_main,
        "parse_csv",
        Mock(side_effect=ValueError("bad csv")),
    )

    with pytest.raises(app_main.CliFatalError):
        app_main.build_transactions(config, logger)
    logger.exception.assert_called_once_with(_MSG_CSV_READ_FAILED)


def test_build_transactions_exits_when_parse_csv_raises_os_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    """入力ファイルの I/O 失敗も明示ログを出して終了する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)

    monkeypatch.setattr(
        app_main,
        "parse_csv",
        Mock(side_effect=PermissionError("denied")),
    )

    with pytest.raises(app_main.CliFatalError):
        app_main.build_transactions(config, logger)
    logger.exception.assert_called_once_with(_MSG_CSV_READ_FAILED)


def test_build_transactions_propagates_unexpected_parse_csv_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    """想定外の実装バグは CliFatalError へ変換せず伝播させる。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)

    monkeypatch.setattr(
        app_main,
        "parse_csv",
        Mock(side_effect=RuntimeError("bug")),
    )

    with pytest.raises(RuntimeError, match="bug"):
        app_main.build_transactions(config, logger)

    logger.exception.assert_not_called()


def test_build_transactions_exits_when_duplicate_history_is_corrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """重複履歴ファイルが破損している場合は明示エラーで終了することを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    transaction = transaction_factory(transaction_id="TX001", merchant="merchant-TX001")

    monkeypatch.setattr(
        app_main,
        "parse_csv",
        Mock(return_value=([transaction], [])),
    )
    monkeypatch.setattr(
        app_main,
        "create_detector",
        Mock(side_effect=DuplicateHistoryError("processed.json が破損しています")),
    )

    with pytest.raises(app_main.CliFatalError):
        app_main.build_transactions(config, logger)
    logger.exception.assert_called_once_with(
        "重複履歴ファイルの読み込みに失敗しました: %s",
        "processed.json が破損しています",
    )


def test_build_transactions_exits_when_duplicate_history_schema_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """不正スキーマの processed.json でも明示エラーで終了することを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    transaction = transaction_factory(transaction_id="TX001", merchant="merchant-TX001")
    processed_file = tmp_path / AppConstants.PROCESSED_FILENAME
    processed_file.write_text(
        "[]",
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )

    monkeypatch.setattr(
        app_main,
        "parse_csv",
        Mock(return_value=([transaction], [])),
    )

    with pytest.raises(app_main.CliFatalError):
        app_main.build_transactions(config, logger)
    logger.exception.assert_called_once()
    log_args = logger.exception.call_args.args
    assert log_args[0] == "重複履歴ファイルの読み込みに失敗しました: %s"
    assert "processed.json が破損しているため読み込めません" in log_args[1]
    backup_files = list(tmp_path.glob("processed.corrupted_*.json"))
    assert len(backup_files) == 1
    assert processed_file.exists() is False


def test_build_transactions_exits_when_gcloud_dependency_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """GCloud optional dependency 未導入時は案内を記録して終了することを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    transaction = transaction_factory(transaction_id="TX001", merchant="merchant-TX001")
    missing_dependency_message = (
        "google-cloud-firestore がインストールされていません。"
        "pip install 'paypay2mf[gcloud]' を実行してください。"
    )

    monkeypatch.setattr(
        app_main,
        "parse_csv",
        Mock(return_value=([transaction], [])),
    )
    monkeypatch.setattr(
        app_main,
        "create_detector",
        Mock(side_effect=ImportError(missing_dependency_message)),
    )

    with pytest.raises(app_main.CliFatalError):
        app_main.build_transactions(config, logger)
    logger.exception.assert_called_once_with(
        _MSG_DUPLICATE_BACKEND_INIT_FAILED,
        missing_dependency_message,
    )


def test_build_transactions_exits_when_gcloud_duplicate_history_doc_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """重複判定中に GCloud 履歴文書異常が起きた場合も明示エラーで終了する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    transaction = transaction_factory(
        transaction_id="TX001",
        merchant="merchant-TX001",
    )
    history_error_message = (
        "Firestore の重複履歴 datetime が不正です: paypay_transactions/bad-doc"
    )
    mark_processed_error = "mark_processed should not be called"
    flush_error = "flush should not be called"

    class _BrokenDetector:
        def is_duplicate(self, _tx: Transaction) -> bool:
            raise DuplicateHistoryError(history_error_message)

        def mark_processed(self, _tx: Transaction) -> None:
            raise AssertionError(mark_processed_error)

        def flush(self) -> None:
            raise AssertionError(flush_error)

    monkeypatch.setattr(
        app_main,
        "parse_csv",
        Mock(return_value=([transaction], [])),
    )
    monkeypatch.setattr(
        app_main,
        "create_detector",
        Mock(return_value=_BrokenDetector()),
    )

    with pytest.raises(app_main.CliFatalError):
        app_main.build_transactions(config, logger)
    logger.exception.assert_called_once_with(
        "重複履歴ファイルの読み込みに失敗しました: %s",
        history_error_message,
    )


def test_run_dry_run_logs_completion() -> None:
    """TC-05-01: dry_run 用 helper が終了ログを出すことを確認する。"""
    logger = Mock(spec=logging.Logger)

    app_main.run_dry_run(logger, 2)

    logger.info.assert_any_call(_MSG_DRY_RUN_COMPLETE, 2)
    logger.info.assert_any_call(_MSG_APP_EXIT)


def test_run_registration_continues_after_item_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """TC-09-03: 個別登録失敗時も残りの取引を継続処理することを確認する。"""
    config = app_config_factory(tmp_path, dry_run=False, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    detector = _FakeDetector()
    registrar = _FakeRegistrar({"TX002"})
    registrar_factory = Mock(return_value=nullcontext(registrar))
    monkeypatch.setattr(app_main, "MFRegistrar", registrar_factory)

    result = app_main.run_registration(
        config,
        logger,
        detector,
        [
            transaction_factory(transaction_id="TX001", merchant="merchant-TX001"),
            transaction_factory(transaction_id="TX002", merchant="merchant-TX002"),
        ],
    )

    assert result.success_count == 1
    assert len(result.failed_records) == 1
    assert result.failed_records[0].error_message == "failed: TX002"
    assert result.failed_records[0].tx.transaction_id == "TX002"
    assert detector.mark_processed.call_count == 1
    detector.flush.assert_called_once_with()
    detector.mark_processed.assert_called_once()
    logger.exception.assert_called_once()
    registrar_factory.assert_called_once_with(config, logger)


def test_register_transaction_log_omits_csv_row_when_row_index_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """TC-09-03b: row_index=0（未設定）の場合、ログに [CSV行 N] が含まれないことを確認する。"""
    config = app_config_factory(tmp_path, dry_run=False, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    detector = _FakeDetector()
    registrar = _FakeRegistrar({"TX001"})
    monkeypatch.setattr(app_main, "MFRegistrar", Mock(return_value=nullcontext(registrar)))

    tx = transaction_factory(transaction_id="TX001", merchant="merchant-TX001", row_index=0)
    app_main.run_registration(config, logger, detector, [tx])

    call_args = logger.exception.call_args
    # logger.exception(_LOG_MSG_REGISTER_FAILED, index, total_count, row_index_str, exc)
    # args: [0]=format_str, [1]=index, [2]=total_count, [3]=row_index_str, [4]=exc
    # row_index=0（未設定）のとき row_index_str が空文字列になることを確認
    assert call_args.args[3] == ""


def test_run_registration_exits_when_registrar_boot_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """TC-09-03: MFRegistrar の起動に失敗した場合に終了することを確認する。"""
    config = app_config_factory(tmp_path, dry_run=False, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    detector = _FakeDetector()

    monkeypatch.setattr(
        app_main,
        "MFRegistrar",
        Mock(side_effect=RuntimeError("boot failed")),
    )

    with pytest.raises(app_main.CliFatalError):
        app_main.run_registration(
            config,
            logger,
            detector,
            [transaction_factory(transaction_id="TX001", merchant="merchant-TX001")],
        )
    detector.flush.assert_called_once_with()
    logger.exception.assert_called_once_with(_MSG_REGISTRATION_BOOT_FAILED)


def test_run_registration_flushes_after_success_even_when_context_exit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """登録後に想定外例外で終了しても成功分の flush を試みることを確認する。"""
    config = app_config_factory(tmp_path, dry_run=False, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    detector = _FakeDetector()
    registrar = _FakeRegistrar()

    class _BrokenRegistrarContext:
        def __enter__(self) -> _FakeRegistrar:
            return registrar

        def __exit__(self, exc_type, exc, tb) -> bool:
            message = _MSG_CONTEXT_EXIT_FAILED
            raise RuntimeError(message)

    monkeypatch.setattr(
        app_main,
        "MFRegistrar",
        Mock(return_value=_BrokenRegistrarContext()),
    )

    with pytest.raises(app_main.CliFatalError):
        app_main.run_registration(
            config,
            logger,
            detector,
            [transaction_factory(transaction_id="TX001", merchant="merchant-TX001")],
        )
    detector.mark_processed.assert_called_once()
    detector.flush.assert_called_once_with()
    logger.exception.assert_called_once_with(_MSG_REGISTRATION_BOOT_FAILED)


def test_run_registration_exits_when_duplicate_history_flush_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """flush 失敗時は全体失敗として終了することを確認する。"""
    config = app_config_factory(tmp_path, dry_run=False, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    detector = _FakeDetector(
        flush_side_effect=DuplicateHistorySaveError(
            "processed.json の保存に失敗しました"
        ),
    )
    registrar = _FakeRegistrar()
    registrar_factory = Mock(return_value=nullcontext(registrar))
    monkeypatch.setattr(app_main, "MFRegistrar", registrar_factory)

    with pytest.raises(app_main.CliFatalError):
        app_main.run_registration(
            config,
            logger,
            detector,
            [transaction_factory(transaction_id="TX001", merchant="merchant-TX001")],
        )
    detector.mark_processed.assert_called_once()
    detector.flush.assert_called_once_with()
    logger.exception.assert_called_once_with(
        _MSG_DUPLICATE_HISTORY_SAVE_FAILED,
        "processed.json の保存に失敗しました",
    )


def test_run_registration_exits_when_duplicate_history_update_fails_after_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """MF 登録成功後に履歴更新が失敗した場合は継続せず終了する。"""
    config = app_config_factory(tmp_path, dry_run=False, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    registrar = _FakeRegistrar()
    registrar_factory = Mock(return_value=nullcontext(registrar))
    tx1 = transaction_factory(transaction_id="TX001", merchant="merchant-TX001")
    tx2 = transaction_factory(transaction_id="TX002", merchant="merchant-TX002")

    class _BrokenDetector:
        def __init__(self) -> None:
            self.mark_processed = Mock(
                side_effect=[RuntimeError("history write failed")]
            )
            self.flush = Mock()

    detector = _BrokenDetector()
    monkeypatch.setattr(app_main, "MFRegistrar", registrar_factory)

    with pytest.raises(app_main.CliFatalError):
        app_main.run_registration(
            config,
            logger,
            detector,
            [tx1, tx2],
        )
    assert registrar.registered == ["TX001"]
    detector.mark_processed.assert_called_once_with(tx1)
    detector.flush.assert_called_once_with()
    logger.exception.assert_called_once_with(
        _MSG_DUPLICATE_HISTORY_UPDATE_FAILED,
        "処理済み履歴の更新に失敗しました (1/2)",
    )


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

    assert app_main.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "設定ファイルの読み込みに失敗しました" in captured.err
    assert "bad config" in captured.err


def test_main_returns_failure_when_build_transactions_raises_cli_fatal_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    """build_transactions の致命エラーは main が終了コード 1 へ正規化する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)

    monkeypatch.setattr(app_main, "load_config", Mock(return_value=config))
    monkeypatch.setattr(app_main, "setup_logger", Mock(return_value=logger))
    monkeypatch.setattr(
        app_main,
        "build_transactions",
        Mock(side_effect=app_main.CliFatalError),
    )

    assert app_main.main([]) == 1


def test_main_returns_failure_when_run_registration_raises_cli_fatal_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """run_registration の致命エラーは main が終了コード 1 を返す。"""
    config = app_config_factory(tmp_path, dry_run=False, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)

    monkeypatch.setattr(app_main, "load_config", Mock(return_value=config))
    monkeypatch.setattr(app_main, "setup_logger", Mock(return_value=logger))
    monkeypatch.setattr(
        app_main,
        "build_transactions",
        Mock(
            return_value=app_main.PreparedTransactions(
                detector=_FakeDetector(),
                to_process=[
                    transaction_factory(
                        transaction_id="TX001",
                        merchant="merchant-TX001",
                    ),
                ],
                excluded_count=0,
                skip_count=0,
            )
        ),
    )
    monkeypatch.setattr(
        app_main,
        "run_registration",
        Mock(side_effect=app_main.CliFatalError),
    )

    assert app_main.main([]) == 1


def test_main_dry_run_skips_browser_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """TC-05-01: dry_run では Chrome 確認と登録処理を呼ばないことを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)

    monkeypatch.setattr(app_main, "load_config", Mock(return_value=config))
    monkeypatch.setattr(app_main, "setup_logger", Mock(return_value=logger))
    build_mock = Mock(
        return_value=app_main.PreparedTransactions(
            detector=_FakeDetector(),
            to_process=[
                transaction_factory(transaction_id="TX001", merchant="merchant-TX001"),
            ],
            excluded_count=0,
            skip_count=0,
        ),
    )
    monkeypatch.setattr(app_main, "build_transactions", build_mock)
    run_dry_run_mock = Mock()
    monkeypatch.setattr(app_main, "run_dry_run", run_dry_run_mock)
    run_registration_mock = Mock()
    monkeypatch.setattr(app_main, "run_registration", run_registration_mock)

    assert app_main.main([]) == 0

    build_mock.assert_called_once_with(config, logger)
    run_dry_run_mock.assert_called_once_with(logger, 1)
    run_registration_mock.assert_not_called()


def test_main_dry_run_does_not_persist_processed_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
    transaction_factory,
) -> None:
    """TC-05-02: dry_run の main フローが重複履歴を汚染しないことを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    transaction = transaction_factory(transaction_id="TX001", merchant="merchant-TX001")

    monkeypatch.setattr(app_main, "load_config", Mock(return_value=config))
    monkeypatch.setattr(app_main, "setup_logger", Mock(return_value=logger))
    monkeypatch.setattr(app_main, "parse_csv", Mock(return_value=([transaction], [])))

    assert app_main.main([]) == 0

    processed_file = tmp_path / AppConstants.PROCESSED_FILENAME
    assert processed_file.exists() is False
    assert LocalDuplicateDetector(config).is_duplicate(transaction) is False


def test_main_uses_cli_config_path_before_env_and_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    """--config 指定が他の探索経路より優先されることを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    cli_config = tmp_path / "cli.yml"
    env_config = tmp_path / "env.yml"
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    (cwd_dir / "config.yml").write_text("", encoding=AppConstants.DEFAULT_TEXT_ENCODING)

    monkeypatch.chdir(cwd_dir)
    monkeypatch.setenv("PAYPAY2MF_CONFIG", str(env_config))
    monkeypatch.setattr(app_main, "load_config", Mock(return_value=config))
    monkeypatch.setattr(app_main, "setup_logger", Mock(return_value=logger))
    monkeypatch.setattr(
        app_main,
        "build_transactions",
        Mock(
            return_value=app_main.PreparedTransactions(
                detector=_FakeDetector(),
                to_process=[],
                excluded_count=0,
                skip_count=0,
            )
        ),
    )
    monkeypatch.setattr(app_main, "run_dry_run", Mock())

    assert app_main.main(["--config", str(cli_config)]) == 0

    app_main.load_config.assert_called_once_with(cli_config)


def test_main_uses_env_config_path_when_cli_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    """CLI 未指定時は PAYPAY2MF_CONFIG を優先することを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    env_config = tmp_path / "env.yml"
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    (cwd_dir / "config.yml").write_text("", encoding=AppConstants.DEFAULT_TEXT_ENCODING)

    monkeypatch.chdir(cwd_dir)
    monkeypatch.setenv("PAYPAY2MF_CONFIG", str(env_config))
    monkeypatch.setattr(app_main, "load_config", Mock(return_value=config))
    monkeypatch.setattr(app_main, "setup_logger", Mock(return_value=logger))
    monkeypatch.setattr(
        app_main,
        "build_transactions",
        Mock(
            return_value=app_main.PreparedTransactions(
                detector=_FakeDetector(),
                to_process=[],
                excluded_count=0,
                skip_count=0,
            )
        ),
    )
    monkeypatch.setattr(app_main, "run_dry_run", Mock())

    assert app_main.main([]) == 0

    app_main.load_config.assert_called_once_with(env_config)


def test_main_uses_cwd_config_path_when_cli_and_env_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    """CLI と環境変数が未指定なら cwd の config.yml を使うことを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    cwd_config = cwd_dir / "config.yml"
    cwd_config.write_text("", encoding=AppConstants.DEFAULT_TEXT_ENCODING)

    monkeypatch.chdir(cwd_dir)
    monkeypatch.delenv("PAYPAY2MF_CONFIG", raising=False)
    monkeypatch.setattr(app_main, "load_config", Mock(return_value=config))
    monkeypatch.setattr(app_main, "setup_logger", Mock(return_value=logger))
    monkeypatch.setattr(
        app_main,
        "build_transactions",
        Mock(
            return_value=app_main.PreparedTransactions(
                detector=_FakeDetector(),
                to_process=[],
                excluded_count=0,
                skip_count=0,
            )
        ),
    )
    monkeypatch.setattr(app_main, "run_dry_run", Mock())

    assert app_main.main([]) == 0

    app_main.load_config.assert_called_once_with(cwd_config)


def test_main_falls_back_to_module_config_path_when_cwd_config_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    """cwd に config.yml が無い場合はモジュール同居へフォールバックすることを確認する。"""
    config = app_config_factory(tmp_path, dry_run=True, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)
    cwd_dir = tmp_path / "cwd"
    module_dir = tmp_path / "module"
    cwd_dir.mkdir()
    module_dir.mkdir()
    module_config = module_dir / "config.yml"
    module_config.write_text("", encoding=AppConstants.DEFAULT_TEXT_ENCODING)

    monkeypatch.chdir(cwd_dir)
    monkeypatch.delenv("PAYPAY2MF_CONFIG", raising=False)
    monkeypatch.setattr(app_main, "__file__", str(module_dir / "main.py"))
    monkeypatch.setattr(app_main, "load_config", Mock(return_value=config))
    monkeypatch.setattr(app_main, "setup_logger", Mock(return_value=logger))
    monkeypatch.setattr(
        app_main,
        "build_transactions",
        Mock(
            return_value=app_main.PreparedTransactions(
                detector=_FakeDetector(),
                to_process=[],
                excluded_count=0,
                skip_count=0,
            )
        ),
    )
    monkeypatch.setattr(app_main, "run_dry_run", Mock())

    assert app_main.main([]) == 0

    app_main.load_config.assert_called_once_with(module_config)


def test_main_returns_zero_when_no_transactions_remain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config_factory,
) -> None:
    """登録対象が 0 件でも正常終了コードを返すことを確認する。"""
    config = app_config_factory(tmp_path, dry_run=False, input_csv_text="header\n")
    logger = Mock(spec=logging.Logger)

    monkeypatch.setattr(app_main, "load_config", Mock(return_value=config))
    monkeypatch.setattr(app_main, "setup_logger", Mock(return_value=logger))
    monkeypatch.setattr(
        app_main,
        "build_transactions",
        Mock(
            return_value=app_main.PreparedTransactions(
                detector=_FakeDetector(),
                to_process=[],
                excluded_count=0,
                skip_count=0,
            )
        ),
    )
    run_registration_mock = Mock()
    monkeypatch.setattr(app_main, "run_registration", run_registration_mock)

    assert app_main.main([]) == 0

    run_registration_mock.assert_not_called()
    logger.info.assert_any_call(_MSG_APP_EXIT)
