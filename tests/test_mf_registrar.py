"""mf_registrar モジュールのテスト。

対応テストレイヤー:
    ui_contract: Fake Page を使った registrar の副作用契約

対応テストケース:
    TC-08-01: セレクタ未検出時のスクリーンショット制御
"""

from __future__ import annotations

import logging
import os
import pathlib
import re

import pytest

import paypay2mf.mf_registrar as mf_registrar_module
from paypay2mf.constants import AppConstants
from paypay2mf.mf_registrar import MFRegistrar

_SELECTOR_TIMEOUT_MESSAGE = "selector timeout"
_SCREENSHOT_STUB = "stub"
_DEFAULT_MERCHANT = "Sample Merchant"
_LOGGER_NAME_OPTOUT = "test-mf-registrar-optout"
_LOGGER_NAME_OPTIN = "test-mf-registrar-optin"
_LOGGER_NAME_NO_PAGE = "test-mf-registrar-no-page"
_LOGGER_NAME_STARTUP = "test-mf-registrar-startup"
_SCREENSHOT_NAME_PATTERN = r"screenshot_\d{8}_\d{6}\.png"
_SCREENSHOT_SAVED_LOG = "スクリーンショットを保存しました"
_SCREENSHOT_SKIPPED_LOG = (
    "Selenium driver が未初期化のため、スクリーンショットを保存しませんでした。"
)
_BOOT_FAILED = "boot failed"
_QUIT_FAILED = "quit failed"
_CHROME_QUIT_FAILED_LOG = "Chrome の終了中に例外が発生しました。"
_LOGGER_NAME_CLOSE = "test-mf-registrar-close"

pytestmark = pytest.mark.ui_contract


class _FailingManualFormPage:
    def register_transaction(self, _tx) -> None:
        raise RuntimeError(_SELECTOR_TIMEOUT_MESSAGE)


class _FakeDriver:
    def __init__(self) -> None:
        self.screenshot_paths: list[str] = []
        self.quit_called = False

    def save_screenshot(self, path: str) -> None:
        self.screenshot_paths.append(path)
        pathlib.Path(path).write_text(
            _SCREENSHOT_STUB,
            encoding=AppConstants.DEFAULT_TEXT_ENCODING,
        )

    def quit(self) -> None:
        self.quit_called = True


class _FailingQuitDriver(_FakeDriver):
    def quit(self) -> None:
        raise RuntimeError(_QUIT_FAILED)


class _FakeOpenableManualFormPage:
    def open(self) -> None:
        return None


def test_register_does_not_save_screenshot_when_opted_out(
    tmp_path: pathlib.Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """TC-08-01: screenshot_on_error=False では例外時も PNG を保存しないことを確認する。"""
    logs_dir = tmp_path / "logs"
    fake_driver = _FakeDriver()
    registrar = MFRegistrar(
        app_config_factory(
            tmp_path,
            screenshot_on_error=False,
            logs_dir=logs_dir,
            input_csv_name="dummy.csv",
        ),
        logging.getLogger(_LOGGER_NAME_OPTOUT),
    )
    object.__setattr__(registrar, "_driver", fake_driver)
    object.__setattr__(registrar, "_manual_form_page", _FailingManualFormPage())

    with pytest.raises(RuntimeError, match=_SELECTOR_TIMEOUT_MESSAGE):
        registrar.register(transaction_factory(merchant=_DEFAULT_MERCHANT))

    assert fake_driver.screenshot_paths == []
    assert not logs_dir.exists()


def test_register_saves_redacted_screenshot_name_when_opted_in(
    tmp_path: pathlib.Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """TC-08-01: screenshot_on_error=True の場合だけ PNG が保存され、ファイル名に加盟店名を含まないことを確認する。"""
    registrar = MFRegistrar(
        app_config_factory(
            tmp_path,
            screenshot_on_error=True,
            input_csv_name="dummy.csv",
        ),
        logging.getLogger(_LOGGER_NAME_OPTIN),
    )
    fake_driver = _FakeDriver()
    object.__setattr__(registrar, "_driver", fake_driver)
    object.__setattr__(registrar, "_manual_form_page", _FailingManualFormPage())

    with pytest.raises(RuntimeError, match=_SELECTOR_TIMEOUT_MESSAGE):
        registrar.register(transaction_factory(merchant=_DEFAULT_MERCHANT))

    assert len(fake_driver.screenshot_paths) == 1
    screenshot_name = pathlib.Path(fake_driver.screenshot_paths[0]).name
    assert re.fullmatch(_SCREENSHOT_NAME_PATTERN, screenshot_name)
    assert _DEFAULT_MERCHANT not in screenshot_name
    assert pathlib.Path(fake_driver.screenshot_paths[0]).exists()


def test_register_logs_warning_without_false_saved_message_when_page_missing(
    tmp_path: pathlib.Path,
    app_config_factory,
    transaction_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """コンテキスト外誤用時は保存済みログを出さず、保存不可 warning のみ出す。"""
    logger = logging.getLogger(_LOGGER_NAME_NO_PAGE)
    registrar = MFRegistrar(
        app_config_factory(
            tmp_path,
            screenshot_on_error=True,
            logs_dir=tmp_path / "logs",
            input_csv_name="dummy.csv",
        ),
        logger,
    )

    with (
        caplog.at_level(logging.WARNING, logger=logger.name),
        pytest.raises(RuntimeError, match="Selenium driver が初期化されていません。"),
    ):
        registrar.register(transaction_factory(merchant=_DEFAULT_MERCHANT))

    assert tuple(
        record.message for record in caplog.records if record.name == logger.name
    ) == (_SCREENSHOT_SKIPPED_LOG,)
    assert not (tmp_path / "logs").exists()


def test_take_screenshot_returns_none_without_creating_files_when_page_missing(
    tmp_path: pathlib.Path,
    app_config_factory,
) -> None:
    """_driver が未初期化ならスクリーンショットを保存せず None を返す。"""
    logs_dir = tmp_path / "logs"
    registrar = MFRegistrar(
        app_config_factory(
            tmp_path,
            screenshot_on_error=True,
            logs_dir=logs_dir,
            input_csv_name="dummy.csv",
        ),
        logging.getLogger(_LOGGER_NAME_NO_PAGE),
    )

    assert registrar._take_screenshot() is None
    assert not logs_dir.exists()
    assert list(tmp_path.glob("screenshot_*.png")) == []


def test_registrar_sets_avoid_stats_only_during_chrome_startup(
    tmp_path: pathlib.Path,
    app_config_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chrome 起動時だけ SE_AVOID_STATS を補完し、終了後に戻す。"""
    observed_value: list[str | None] = []
    observed_page_load_strategy: list[str] = []
    fake_driver = _FakeDriver()

    def _fake_chrome(*, options) -> object:
        observed_value.append(os.environ.get("SE_AVOID_STATS"))
        observed_page_load_strategy.append(options.page_load_strategy)
        return fake_driver

    monkeypatch.delenv("SE_AVOID_STATS", raising=False)
    monkeypatch.setattr(mf_registrar_module, "Chrome", _fake_chrome)
    monkeypatch.setattr(MFRegistrar, "_open_moneyforward_page", lambda _self: None)
    monkeypatch.setattr(MFRegistrar, "_wait_for_manual_login", lambda _self: None)
    monkeypatch.setattr(MFRegistrar, "_open_household_book_tab", lambda _self: None)
    monkeypatch.setattr(
        MFRegistrar,
        "_build_manual_form_page",
        lambda _self: _FakeOpenableManualFormPage(),
    )

    registrar = MFRegistrar(
        app_config_factory(tmp_path, input_csv_name="dummy.csv"),
        logging.getLogger(_LOGGER_NAME_STARTUP),
    )

    with registrar:
        assert observed_value == ["true"]
        assert observed_page_load_strategy == ["eager"]
        assert os.environ.get("SE_AVOID_STATS") is None

    assert fake_driver.quit_called is True


def test_registrar_preserves_existing_avoid_stats(
    tmp_path: pathlib.Path,
    app_config_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """既存の SE_AVOID_STATS は上書きせずに Chrome 起動へ渡す。"""
    observed_value: list[str | None] = []

    def _fake_chrome(*, options) -> _FakeDriver:
        del options
        observed_value.append(os.environ.get("SE_AVOID_STATS"))
        return _FakeDriver()

    monkeypatch.setenv("SE_AVOID_STATS", "false")
    monkeypatch.setattr(mf_registrar_module, "Chrome", _fake_chrome)
    monkeypatch.setattr(MFRegistrar, "_open_moneyforward_page", lambda _self: None)
    monkeypatch.setattr(MFRegistrar, "_wait_for_manual_login", lambda _self: None)
    monkeypatch.setattr(MFRegistrar, "_open_household_book_tab", lambda _self: None)
    monkeypatch.setattr(
        MFRegistrar,
        "_build_manual_form_page",
        lambda _self: _FakeOpenableManualFormPage(),
    )

    registrar = MFRegistrar(
        app_config_factory(tmp_path, input_csv_name="dummy.csv"),
        logging.getLogger(_LOGGER_NAME_STARTUP),
    )

    with registrar:
        assert observed_value == ["false"]

    assert os.environ.get("SE_AVOID_STATS") == "false"


def test_registrar_restores_env_after_chrome_boot_failure(
    tmp_path: pathlib.Path,
    app_config_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chrome 起動失敗時も一時注入した SE_AVOID_STATS を残さない。"""

    def _failing_chrome(*, options) -> None:
        del options
        assert os.environ.get("SE_AVOID_STATS") == "true"
        raise RuntimeError(_BOOT_FAILED)

    monkeypatch.delenv("SE_AVOID_STATS", raising=False)
    monkeypatch.setattr(mf_registrar_module, "Chrome", _failing_chrome)

    registrar = MFRegistrar(
        app_config_factory(tmp_path, input_csv_name="dummy.csv"),
        logging.getLogger(_LOGGER_NAME_STARTUP),
    )

    with pytest.raises(RuntimeError, match=_BOOT_FAILED):
        registrar.__enter__()

    assert os.environ.get("SE_AVOID_STATS") is None


def test_enter_cleans_up_temp_profile_dir_on_chrome_boot_failure(
    tmp_path: pathlib.Path,
    app_config_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chrome 起動失敗時、一時プロファイルディレクトリが削除されることを確認する。"""

    def _failing_chrome(*, options) -> None:
        del options
        raise RuntimeError(_BOOT_FAILED)

    monkeypatch.setattr(mf_registrar_module, "Chrome", _failing_chrome)

    registrar = MFRegistrar(
        app_config_factory(tmp_path, input_csv_name="dummy.csv"),
        logging.getLogger(_LOGGER_NAME_STARTUP),
    )

    with pytest.raises(RuntimeError, match=_BOOT_FAILED):
        registrar.__enter__()

    # _temporary_profile_dir is still set after __enter__ raises, but the dir must be gone
    assert registrar._temporary_profile_dir is not None
    assert not registrar._temporary_profile_dir.exists(), "一時プロファイルディレクトリは削除されるべき"


def test_close_suppresses_quit_exception_and_logs_warning(
    tmp_path: pathlib.Path,
    app_config_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """quit() が例外を投げても _close() は例外を伝播させず warning をログに残し、一時ディレクトリを削除する。"""
    logger = logging.getLogger(_LOGGER_NAME_CLOSE)
    registrar = MFRegistrar(
        app_config_factory(tmp_path, input_csv_name="dummy.csv"),
        logger,
    )
    profile_dir = tmp_path / "fake-profile"
    profile_dir.mkdir()
    registrar._driver = _FailingQuitDriver()
    registrar._temporary_profile_dir = profile_dir

    with caplog.at_level(logging.WARNING, logger=logger.name):
        registrar._close()  # must not raise

    assert not profile_dir.exists(), "一時プロファイルディレクトリは削除されるべき"
    warning_messages = [
        record.message
        for record in caplog.records
        if record.name == logger.name and record.levelno == logging.WARNING
    ]
    assert any(_CHROME_QUIT_FAILED_LOG in msg for msg in warning_messages)
