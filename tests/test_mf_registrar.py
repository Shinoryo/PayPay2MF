"""mf_registrar モジュールのテスト。

対応テストレイヤー:
    ui_contract: Fake Page を使った registrar の副作用契約

対応テストケース:
    TC-08-01: セレクタ未検出時のスクリーンショット制御
"""

from __future__ import annotations

import logging
import pathlib
import re

import pytest

from paypay2mf.constants import AppConstants
from paypay2mf.mf_registrar import MFRegistrar

_SELECTOR_TIMEOUT_MESSAGE = "selector timeout"
_SCREENSHOT_STUB = "stub"
_DEFAULT_MERCHANT = "Sample Merchant"
_LOGGER_NAME_OPTOUT = "test-mf-registrar-optout"
_LOGGER_NAME_OPTIN = "test-mf-registrar-optin"
_LOGGER_NAME_NO_PAGE = "test-mf-registrar-no-page"
_SCREENSHOT_NAME_PATTERN = r"screenshot_\d{8}_\d{6}\.png"
_SCREENSHOT_SAVED_LOG = "スクリーンショットを保存しました"
_SCREENSHOT_SKIPPED_LOG = (
    "Selenium driver が未初期化のため、スクリーンショットを保存しませんでした。"
)

pytestmark = pytest.mark.ui_contract


class _FailingManualFormPage:
    def register_transaction(self, _tx) -> None:
        raise RuntimeError(_SELECTOR_TIMEOUT_MESSAGE)


class _FakeDriver:
    def __init__(self) -> None:
        self.screenshot_paths: list[str] = []

    def save_screenshot(self, path: str) -> None:
        self.screenshot_paths.append(path)
        pathlib.Path(path).write_text(
            _SCREENSHOT_STUB,
            encoding=AppConstants.DEFAULT_TEXT_ENCODING,
        )


def test_register_does_not_save_screenshot_when_opted_out(
    tmp_path: pathlib.Path,
    app_config_factory,
    transaction_factory,
) -> None:
    """TC-08-01: screenshot_on_error=False では例外時も PNG を保存しないことを確認する。"""
    registrar = MFRegistrar(
        app_config_factory(
            tmp_path,
            screenshot_on_error=False,
            input_csv_name="dummy.csv",
        ),
        logging.getLogger(_LOGGER_NAME_OPTOUT),
    )
    object.__setattr__(registrar, "_manual_form_page", _FailingManualFormPage())

    with pytest.raises(RuntimeError, match=_SELECTOR_TIMEOUT_MESSAGE):
        registrar.register(transaction_factory(merchant=_DEFAULT_MERCHANT))

    assert registrar._take_screenshot() is None


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

    with caplog.at_level(logging.WARNING, logger=logger.name):
        with pytest.raises(RuntimeError, match="Selenium driver が初期化されていません。"):
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
