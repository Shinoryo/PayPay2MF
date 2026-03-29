"""Money Forward UI 契約のスモークテスト。

対応テストケース:
    TC-07-00: Playwright スモークテスト（手入力モーダル起動確認）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from paypay2mf.mf_registrar import MFRegistrar

if TYPE_CHECKING:
    from paypay2mf.models import AppConfig


@pytest.mark.smoke_test
def test_can_open_moneyforward_manual_form(mf_smoke_config: AppConfig) -> None:
    """TC-07-00: ログイン済みプロファイルで手入力モーダルを開けることを確認する。"""
    logger = logging.getLogger("paypay2mf-smoke")

    with MFRegistrar(mf_smoke_config, logger) as registrar:
        modal = registrar.open_manual_form()

    assert modal is not None
