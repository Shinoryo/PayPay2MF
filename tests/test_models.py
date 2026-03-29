"""models モジュールの既定値テスト。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.constants import AppConstants
from src.models import (
    AppConfig,
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


def test_dataclass_defaults_match_app_constants(tmp_path: Path) -> None:
    csv_file = tmp_path / _INPUT_CSV_FILENAME
    csv_file.write_text(
        AppConstants.EMPTY_STRING,
        encoding=AppConstants.DEFAULT_TEXT_ENCODING,
    )

    mapping_rule = MappingRule(keyword=_DEFAULT_KEYWORD, category=_DEFAULT_RULE_CATEGORY)
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
    config = AppConfig(
        chrome_user_data_dir=_DUMMY_CHROME_USER_DATA_DIR,
        chrome_profile=_DEFAULT_CHROME_PROFILE,
        dry_run=True,
        input_csv=csv_file,
        mf_account=_DEFAULT_MF_ACCOUNT,
    )

    assert mapping_rule.match_mode == AppConstants.DEFAULT_MATCH_MODE
    assert transaction.category == AppConstants.DEFAULT_CATEGORY
    assert duplicate_detection.backend == AppConstants.DEFAULT_BACKEND
    assert parser.encoding_priority == list(AppConstants.DEFAULT_ENCODING_PRIORITY)
    assert parser.date_formats == list(AppConstants.DEFAULT_DATE_FORMATS)
    assert config.exclude_prefixes == list(AppConstants.DEFAULT_EXCLUDE_PREFIXES)
