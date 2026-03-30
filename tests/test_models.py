"""models モジュールの既定値テスト。

共通テストデータ生成の基礎整合性を確認する。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from paypay2mf.constants import AppConstants
from paypay2mf.models import (
    DuplicateDetectionConfig,
    MappingRule,
    ParserConfig,
    Transaction,
)

_DUMMY_CHROME_USER_DATA_DIR = "C:\\dummy"
_DEFAULT_CHROME_PROFILE = "Default"
_DEFAULT_MF_ACCOUNT = "PayPay残高"
_INPUT_CSV_FILENAME = "dummy.csv"
_DEFAULT_KEYWORD = "keyword"
_DEFAULT_RULE_CATEGORY = "category"
_DEFAULT_MEMO = "memo"
_DEFAULT_MERCHANT = "merchant"
_DEFAULT_TRANSACTION_ID = "TX001"

if TYPE_CHECKING:
    from pathlib import Path


def test_dataclass_defaults_match_app_constants(
    tmp_path: Path,
    app_config_factory,
) -> None:
    """dataclass の既定値が AppConstants と整合することを確認する。"""

    mapping_rule = MappingRule(
        keyword=_DEFAULT_KEYWORD, category=_DEFAULT_RULE_CATEGORY
    )
    transaction = Transaction(
        date=datetime(2025, 1, 1, 12, 0, 0),  # noqa: DTZ001
        amount=100,
        direction=AppConstants.DIRECTION_OUT,
        memo=_DEFAULT_MEMO,
        merchant=_DEFAULT_MERCHANT,
        transaction_id=_DEFAULT_TRANSACTION_ID,
    )
    duplicate_detection = DuplicateDetectionConfig()
    parser = ParserConfig()
    config = app_config_factory(
        tmp_path, dry_run=True, input_csv_name=_INPUT_CSV_FILENAME
    )

    assert mapping_rule.match_mode == AppConstants.DEFAULT_MATCH_MODE
    assert transaction.category == AppConstants.DEFAULT_CATEGORY
    assert duplicate_detection.backend == AppConstants.DEFAULT_BACKEND
    assert parser.encoding_priority == list(AppConstants.DEFAULT_ENCODING_PRIORITY)
    assert parser.date_formats == list(AppConstants.DEFAULT_DATE_FORMATS)
    assert config.exclude_prefixes == list(AppConstants.DEFAULT_EXCLUDE_PREFIXES)
