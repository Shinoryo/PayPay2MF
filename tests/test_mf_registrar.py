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

from src.constants import AppConstants
from src.mf_registrar import MFRegistrar

_SELECTOR_TIMEOUT_MESSAGE = "selector timeout"
_SCREENSHOT_STUB = "stub"
_DEFAULT_MERCHANT = "Sample Merchant"
_LOGGER_NAME_OPTOUT = "test-mf-registrar-optout"
_LOGGER_NAME_OPTIN = "test-mf-registrar-optin"
_SCREENSHOT_NAME_PATTERN = r"screenshot_\d{8}_\d{6}\.png"

pytestmark = pytest.mark.ui_contract


class _FakePage:
    def __init__(self) -> None:
        self.screenshot_paths: list[str] = []

    def click(self, _selector: str) -> None:
        raise RuntimeError(_SELECTOR_TIMEOUT_MESSAGE)

    def screenshot(self, path: str) -> None:
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
    fake_page = _FakePage()
    object.__setattr__(registrar, "_page", fake_page)

    with pytest.raises(RuntimeError, match=_SELECTOR_TIMEOUT_MESSAGE):
        registrar.register(transaction_factory(merchant=_DEFAULT_MERCHANT))

    assert fake_page.screenshot_paths == []


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
    fake_page = _FakePage()
    object.__setattr__(registrar, "_page", fake_page)

    with pytest.raises(RuntimeError, match=_SELECTOR_TIMEOUT_MESSAGE):
        registrar.register(transaction_factory(merchant=_DEFAULT_MERCHANT))

    assert len(fake_page.screenshot_paths) == 1
    screenshot_name = pathlib.Path(fake_page.screenshot_paths[0]).name
    assert re.fullmatch(_SCREENSHOT_NAME_PATTERN, screenshot_name)
    assert _DEFAULT_MERCHANT not in screenshot_name
    assert pathlib.Path(fake_page.screenshot_paths[0]).exists()
