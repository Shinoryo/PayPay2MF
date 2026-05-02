"""pytest 共通設定。

共通 factory fixture と smoke_test の実行制御を提供する。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from paypay2mf.constants import AppConstants
from paypay2mf.duplicate_detector import build_row_fingerprint
from paypay2mf.models import (
    AdvancedConfig,
    AppConfig,
    LogSettings,
    ParseFailure,
    Transaction,
)

_DEFAULT_MF_ACCOUNT = "PayPay残高"
_DEFAULT_INPUT_CSV_FILENAME = "input.csv"
_DEFAULT_TRANSACTION_ID = "TX001"
_DEFAULT_MERCHANT = "テスト商店"
_DEFAULT_MEMO = "支払い"

_RUN_SMOKE_ENV = "PAYPAY2MF_RUN_SMOKE_TEST"
_MF_ACCOUNT_ENV = "PAYPAY2MF_SMOKE_MF_ACCOUNT"
_LOGS_DIR_ENV = "PAYPAY2MF_SMOKE_LOGS_DIR"
_SMOKE_MARK_NAME = "smoke_test"
_SMOKE_ENABLED_VALUE = "1"
_SMOKE_LOG_DIR_PREFIX = "mf-smoke-logs"
_SMOKE_PLACEHOLDER_CSV = "smoke-placeholder.csv"

AppConfigFactory = Callable[..., AppConfig]
TransactionFactory = Callable[..., Transaction]
ParseFailureFactory = Callable[..., ParseFailure]


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """明示実行でない smoke_test を自動 skip する。"""
    run_smoke = os.getenv(_RUN_SMOKE_ENV) == _SMOKE_ENABLED_VALUE
    smoke_selected = _SMOKE_MARK_NAME in (
        config.option.markexpr or AppConstants.EMPTY_STRING
    )
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
        dry_run=False,
        input_csv=input_csv,
        mf_account=os.getenv(_MF_ACCOUNT_ENV, _DEFAULT_MF_ACCOUNT),
        log_settings=LogSettings(logs_dir=logs_dir),
        advanced=AdvancedConfig(screenshot_on_error=False),
    )


@pytest.fixture
def app_config_factory() -> AppConfigFactory:
    """単体・結合テスト共通の AppConfig 生成関数を返す。"""

    def _make_config(
        tmp_path: Path,
        *,
        dry_run: bool = False,
        screenshot_on_error: bool = False,
        logs_dir: Path | None = None,
        input_csv_name: str = _DEFAULT_INPUT_CSV_FILENAME,
        input_csv_text: str = AppConstants.EMPTY_STRING,
        mf_account: str = _DEFAULT_MF_ACCOUNT,
    ) -> AppConfig:
        csv_file = tmp_path / input_csv_name
        csv_file.write_text(
            input_csv_text,
            encoding=AppConstants.DEFAULT_TEXT_ENCODING,
        )
        return AppConfig(
            dry_run=dry_run,
            input_csv=csv_file,
            mf_account=mf_account,
            log_settings=LogSettings(logs_dir=logs_dir or tmp_path),
            advanced=AdvancedConfig(screenshot_on_error=screenshot_on_error),
        )

    return _make_config


@pytest.fixture
def transaction_factory() -> TransactionFactory:
    """単体・結合テスト共通の Transaction 生成関数を返す。"""

    def _make_transaction(
        *,
        transaction_id: str | None = _DEFAULT_TRANSACTION_ID,
        merchant: str = _DEFAULT_MERCHANT,
        amount: int = 100,
        date: datetime | None = None,
        date_text: str | None = None,
        memo: str = _DEFAULT_MEMO,
        content: str = "支払い",
        method: str = "PayPay残高",
        payment_type: str = AppConstants.HYPHEN,
        user: str = AppConstants.HYPHEN,
        row_fingerprint: str | None = None,
        category: str = AppConstants.DEFAULT_CATEGORY,
        direction: str = AppConstants.DIRECTION_OUT,
        row_index: int = 0,
    ) -> Transaction:
        resolved_date = date or datetime(2025, 1, 1, 12, 0, 0)  # noqa: DTZ001
        resolved_date_text = date_text or resolved_date.strftime("%Y/%m/%d %H:%M:%S")
        out_amount = amount if direction == AppConstants.DIRECTION_OUT else 0
        in_amount = amount if direction == AppConstants.DIRECTION_IN else 0
        resolved_fingerprint = (
            row_fingerprint
            if row_fingerprint is not None
            else build_row_fingerprint(
                date_text=resolved_date_text,
                content=content,
                merchant=merchant,
                out_amount=out_amount,
                in_amount=in_amount,
                method=method,
                payment_type=payment_type,
                user=user,
            )
        )
        return Transaction(
            date=resolved_date,
            amount=amount,
            direction=direction,
            memo=memo,
            merchant=merchant,
            transaction_id=transaction_id,
            date_text=resolved_date_text,
            content=content,
            method=method,
            payment_type=payment_type,
            user=user,
            row_fingerprint=resolved_fingerprint,
            category=category,
            row_index=row_index,
        )

    return _make_transaction


@pytest.fixture
def parse_failure_factory() -> ParseFailureFactory:
    """単体・結合テスト共通の ParseFailure 生成関数を返す。"""

    def _make_parse_failure(
        *,
        row_index: int = 3,
        transaction_id: str | None = _DEFAULT_TRANSACTION_ID,
        merchant: str | None = _DEFAULT_MERCHANT,
        error_type: str = "parse_error",
        error_message: str = "bad row",
        raw_row: dict[str, str] | None = None,
    ) -> ParseFailure:
        return ParseFailure(
            row_index=row_index,
            transaction_id=transaction_id,
            merchant=merchant,
            error_type=error_type,
            error_message=error_message,
            raw_row=raw_row or {"取引先": merchant or AppConstants.EMPTY_STRING},
        )

    return _make_parse_failure
