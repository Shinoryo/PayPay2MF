"""Money Forward UI 契約のスモークテスト。"""

from __future__ import annotations

import logging

import pytest

from src.mf_registrar import MFRegistrar
from src.models import AppConfig


@pytest.mark.smoke_test
def test_can_open_moneyforward_manual_form(mf_smoke_config: AppConfig) -> None:
    """ログイン済みプロファイルで手入力モーダルを開けることを確認する。"""
    logger = logging.getLogger("paypay2mf-smoke")

    with MFRegistrar(mf_smoke_config, logger) as registrar:
        modal = registrar.open_manual_form()

    assert modal is not None
