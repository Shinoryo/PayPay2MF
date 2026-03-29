"""pytest 共通設定。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.constants import AppConstants
from src.models import AdvancedConfig, AppConfig, LogSettings

_RUN_SMOKE_ENV = "PAYPAY2MF_RUN_SMOKE_TEST"
_CHROME_USER_DATA_ENV = "PAYPAY2MF_SMOKE_CHROME_USER_DATA_DIR"
_CHROME_PROFILE_ENV = "PAYPAY2MF_SMOKE_CHROME_PROFILE"
_MF_ACCOUNT_ENV = "PAYPAY2MF_SMOKE_MF_ACCOUNT"
_LOGS_DIR_ENV = "PAYPAY2MF_SMOKE_LOGS_DIR"
_SMOKE_MARK_NAME = "smoke_test"
_SMOKE_ENABLED_VALUE = "1"
_SMOKE_LOG_DIR_PREFIX = "mf-smoke-logs"
_SMOKE_PLACEHOLDER_CSV = "smoke-placeholder.csv"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """明示実行でない smoke_test を自動 skip する。"""
    run_smoke = os.getenv(_RUN_SMOKE_ENV) == _SMOKE_ENABLED_VALUE
    smoke_selected = _SMOKE_MARK_NAME in (config.option.markexpr or AppConstants.EMPTY_STRING)
    if run_smoke and smoke_selected:
        return

    skip_marker = pytest.mark.skip(
        reason=(
            "smoke_test は明示実行専用です。"
            f"{_RUN_SMOKE_ENV}=1 を設定し、pytest -m smoke_test で実行してください。"
        ),
    )
    for item in items:
        if _SMOKE_MARK_NAME in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture
def mf_smoke_config(tmp_path_factory: pytest.TempPathFactory) -> AppConfig:
    """Money Forward スモークテスト用の AppConfig を返す。"""
    missing = [
        env_name
        for env_name in (_CHROME_USER_DATA_ENV, _CHROME_PROFILE_ENV, _MF_ACCOUNT_ENV)
        if not os.getenv(env_name)
    ]
    if missing:
        pytest.skip(
            "smoke_test 用の環境変数が不足しています: " + ", ".join(missing),
        )

    logs_dir_raw = os.getenv(_LOGS_DIR_ENV)
    logs_dir = (
        Path(logs_dir_raw)
        if logs_dir_raw
        else tmp_path_factory.mktemp(_SMOKE_LOG_DIR_PREFIX)
    )
    input_csv = logs_dir / _SMOKE_PLACEHOLDER_CSV
    input_csv.write_text(
        AppConstants.EMPTY_STRING,
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )

    return AppConfig(
        chrome_user_data_dir=os.environ[_CHROME_USER_DATA_ENV],
        chrome_profile=os.environ[_CHROME_PROFILE_ENV],
        dry_run=False,
        input_csv=input_csv,
        mf_account=os.environ[_MF_ACCOUNT_ENV],
        log_settings=LogSettings(logs_dir=logs_dir),
        advanced=AdvancedConfig(screenshot_on_error=False),
    )
