"""mf_registrar モジュールのテスト。"""

from __future__ import annotations

import logging
import pathlib
import re
from datetime import datetime

import pytest

from src.constants import AppConstants
from src.mf_registrar import MFRegistrar
from src.models import AdvancedConfig, AppConfig, LogSettings, Transaction

_SELECTOR_TIMEOUT_MESSAGE = "selector timeout"
_SCREENSHOT_STUB = "stub"
_DUMMY_CHROME_USER_DATA_DIR = "C:\\dummy"
_DEFAULT_CHROME_PROFILE = "Default"
_DEFAULT_MF_ACCOUNT = "PayPay残高"
_INPUT_CSV_FILENAME = "dummy.csv"
_DEFAULT_MEMO = "支払い"
_DEFAULT_MERCHANT = "Secret Merchant"
_DEFAULT_TRANSACTION_ID = "TX001"
_LOGGER_NAME_OPTOUT = "test-mf-registrar-optout"
_LOGGER_NAME_OPTIN = "test-mf-registrar-optin"
_SCREENSHOT_NAME_PATTERN = r"screenshot_\d{8}_\d{6}\.png"
_SECRET_MARKER = "Secret"


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


def _make_config(
    tmp_path: pathlib.Path,
    *,
    screenshot_on_error: bool,
) -> AppConfig:
    csv_file = tmp_path / _INPUT_CSV_FILENAME
    csv_file.write_text(
        AppConstants.EMPTY_STRING,
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )
    return AppConfig(
        chrome_user_data_dir=_DUMMY_CHROME_USER_DATA_DIR,
        chrome_profile=_DEFAULT_CHROME_PROFILE,
        dry_run=False,
        input_csv=csv_file,
        mf_account=_DEFAULT_MF_ACCOUNT,
        log_settings=LogSettings(logs_dir=tmp_path),
        advanced=AdvancedConfig(screenshot_on_error=screenshot_on_error),
    )


def _make_tx() -> Transaction:
    return Transaction(
        date=datetime(2025, 1, 1, 12, 0, 0),  # noqa: DTZ001
        amount=100,
        direction=AppConstants.DIRECTION_OUT,
        memo=_DEFAULT_MEMO,
        merchant=_DEFAULT_MERCHANT,
        transaction_id=_DEFAULT_TRANSACTION_ID,
    )


def test_register_does_not_save_screenshot_when_opted_out(
    tmp_path: pathlib.Path,
) -> None:
    """screenshot_on_error=False では例外時も PNG を保存しないことを確認する。"""
    registrar = MFRegistrar(
        _make_config(tmp_path, screenshot_on_error=False),
        logging.getLogger(_LOGGER_NAME_OPTOUT),
    )
    fake_page = _FakePage()
    object.__setattr__(registrar, "_page", fake_page)

    with pytest.raises(RuntimeError, match=_SELECTOR_TIMEOUT_MESSAGE):
        registrar.register(_make_tx())

    assert fake_page.screenshot_paths == []


def test_register_saves_redacted_screenshot_name_when_opted_in(
    tmp_path: pathlib.Path,
) -> None:
    """screenshot_on_error=True の場合だけ PNG が保存され、ファイル名に加盟店名を含まないことを確認する。"""
    registrar = MFRegistrar(
        _make_config(tmp_path, screenshot_on_error=True),
        logging.getLogger(_LOGGER_NAME_OPTIN),
    )
    fake_page = _FakePage()
    object.__setattr__(registrar, "_page", fake_page)

    with pytest.raises(RuntimeError, match=_SELECTOR_TIMEOUT_MESSAGE):
        registrar.register(_make_tx())

    assert len(fake_page.screenshot_paths) == 1
    screenshot_name = pathlib.Path(fake_page.screenshot_paths[0]).name
    assert re.fullmatch(_SCREENSHOT_NAME_PATTERN, screenshot_name)
    assert _SECRET_MARKER not in screenshot_name
    assert pathlib.Path(fake_page.screenshot_paths[0]).exists()
