"""mf_registrar モジュールのテスト。"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import pytest

from src.mf_registrar import MFRegistrar
from src.models import AdvancedConfig, AppConfig, LogSettings, Transaction


class _FakePage:
    def __init__(self) -> None:
        self.screenshot_paths: list[str] = []

    def click(self, _selector: str) -> None:
        raise RuntimeError("selector timeout")

    def screenshot(self, path: str) -> None:
        self.screenshot_paths.append(path)
        Path(path).write_text("stub", encoding="utf-8")


def _make_config(tmp_path: Path, *, screenshot_on_error: bool) -> AppConfig:
    csv_file = tmp_path / "dummy.csv"
    csv_file.write_text("", encoding="utf-8")
    return AppConfig(
        chrome_user_data_dir="C:\\dummy",
        chrome_profile="Default",
        dry_run=False,
        input_csv=csv_file,
        mf_account="PayPay残高",
        log_settings=LogSettings(logs_dir=tmp_path),
        advanced=AdvancedConfig(screenshot_on_error=screenshot_on_error),
    )


def _make_tx() -> Transaction:
    return Transaction(
        date=datetime(2025, 1, 1, 12, 0, 0),  # noqa: DTZ001
        amount=100,
        direction="out",
        memo="支払い",
        merchant="Secret Merchant",
        transaction_id="TX001",
    )


def test_register_does_not_save_screenshot_when_opted_out(tmp_path: Path) -> None:
    """screenshot_on_error=False では例外時も PNG を保存しないことを確認する。"""
    registrar = MFRegistrar(
        _make_config(tmp_path, screenshot_on_error=False),
        logging.getLogger("test-mf-registrar-optout"),
    )
    fake_page = _FakePage()
    registrar._page = fake_page

    with pytest.raises(RuntimeError, match="selector timeout"):
        registrar.register(_make_tx())

    assert fake_page.screenshot_paths == []


def test_register_saves_redacted_screenshot_name_when_opted_in(tmp_path: Path) -> None:
    """screenshot_on_error=True の場合だけ PNG が保存され、ファイル名に加盟店名を含まないことを確認する。"""
    registrar = MFRegistrar(
        _make_config(tmp_path, screenshot_on_error=True),
        logging.getLogger("test-mf-registrar-optin"),
    )
    fake_page = _FakePage()
    registrar._page = fake_page

    with pytest.raises(RuntimeError, match="selector timeout"):
        registrar.register(_make_tx())

    assert len(fake_page.screenshot_paths) == 1
    screenshot_name = Path(fake_page.screenshot_paths[0]).name
    assert re.fullmatch(r"screenshot_\d{8}_\d{6}\.png", screenshot_name)
    assert "Secret" not in screenshot_name
    assert Path(fake_page.screenshot_paths[0]).exists()
