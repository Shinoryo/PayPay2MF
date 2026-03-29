"""csv_parser モジュールのテスト。

対応テストケース:
    TC-02-01: 通常の支払い取引のパース
    TC-02-02: カンマを含む金額文字列の数値化
    TC-02-03: 複合支払い（同一取引番号の複数行）の集約
    TC-02-04: ポイント入金のパース
    TC-02-05: UTF-8 エンコーディング
    TC-02-06: Shift_JIS エンコーディング
    TC-02-07: BOM 付き UTF-8 エンコーディング
    TC-02-08: 出金額・入金額が両方0の行の拒否
    TC-02-09: 出金額・入金額が両方正数の行の拒否
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.constants import AppConstants
from src.csv_parser import _merge_compound, _parse_amount, parse_csv
from src.models import AppConfig

_DUMMY_CHROME_USER_DATA_DIR = "C:\\dummy"
_DEFAULT_CHROME_PROFILE = "Default"
_DEFAULT_MF_ACCOUNT = "PayPay残高"
_FIXTURE_DIRNAME = "fixtures"
_INPUT_CSV_FILENAME = "test_input.csv"
_INPUT_SJIS_CSV_FILENAME = "test_input_sjis.csv"
_COMPOUND_CSV_FILENAME = "compound.csv"
_BOM_CSV_FILENAME = "bom.csv"
_MIXED_CSV_FILENAME = "mixed.csv"
_MIXED_BOM_CSV_FILENAME = "mixed_bom.csv"
_MISSING_COLUMN_CSV_FILENAME = "missing_column.csv"
_MOS_TRANSACTION_ID = "04639628474580213761"
_GIFTEE_TRANSACTION_ID = "856574761326657536-a0196d18"
_GOOGLE_TRANSACTION_ID = "PPCD_A_2025021122321300218846"
_OK_TRANSACTION_ID = "OK001"
_BAD_TRANSACTION_ID = "BAD001"
_BOM_TRANSACTION_ID = "BOM001"
_COMPOUND_TRANSACTION_ID = "04638686270424956930"
_MOS_MERCHANT = "モスのネット注文"
_GIFTEE_MERCHANT = "giftee"
_COMPOUND_MERCHANT = "キャンドゥ　横浜橋商店街"
_FOREIGN_MEMO_MARKER = "海外"
_JPY_CURRENCY = "JPY"
_PARSE_ERROR_INVALID_DATE = "invalid_date"
_PARSE_ERROR_INVALID_VALUE = "invalid_value"
_PARSE_ERROR_MISSING_COLUMN = "missing_column"
_TRADE_DATE_COLUMN = "取引日"


def _make_config(csv_path: Path) -> AppConfig:
    """テスト用の AppConfig を生成する。

    Args:
        csv_path: input_csv に設定するパス。

    Returns:
        テスト用 AppConfig インスタンス。
    """
    return AppConfig(
        chrome_user_data_dir=_DUMMY_CHROME_USER_DATA_DIR,
        chrome_profile=_DEFAULT_CHROME_PROFILE,
        dry_run=True,
        input_csv=csv_path,
        mf_account=_DEFAULT_MF_ACCOUNT,
    )


FIXTURE_DIR = Path(__file__).parent / _FIXTURE_DIRNAME


# TC-02-01: 通常支払（モス 920円）
def test_parse_normal_payment() -> None:
    """TC-02-01: 通常の支払い取引（モス 920円）が正しくパースされることを確認する。"""
    txs, failures = parse_csv(
        FIXTURE_DIR / _INPUT_CSV_FILENAME,
        _make_config(FIXTURE_DIR / _INPUT_CSV_FILENAME),
    )
    assert failures == []
    mos = next(t for t in txs if t.transaction_id == _MOS_TRANSACTION_ID)
    assert mos.date == datetime(2025, 2, 11, 19, 24, 2)  # noqa: DTZ001
    assert mos.amount == 920
    assert mos.direction == AppConstants.DIRECTION_OUT
    assert mos.merchant == _MOS_MERCHANT


# TC-02-02: カンマ含む金額文字列の数値化
def test_parse_amount_with_comma() -> None:
    """TC-02-02: カンマを含む金額文字列が整数に正しく変換されることを確認する。"""
    assert _parse_amount('"1,280"') == 1280
    assert _parse_amount("1,280") == 1280
    assert _parse_amount(AppConstants.HYPHEN) == 0
    assert _parse_amount(AppConstants.EMPTY_STRING) == 0
    assert _parse_amount("920") == 920


# TC-02-03: 複合支払の合算（キャンドゥ 73+257=330円）
def test_parse_compound_payment(tmp_path: Path) -> None:
    """TC-02-03: 同一取引番号の複数行が合算されて1件になることを確認する（キャンドゥ 73+257=330円）。"""
    csv_content = (
        "取引日,出金金額（円）,入金金額（円）,海外出金金額,通貨,変換レート（円）,"
        "利用国,取引内容,取引先,取引方法,支払い区分,利用者,取引番号\r\n"
        "2025/02/10 12:55:55,73,-,-,-,-,-,支払い,キャンドゥ　横浜橋商店街,"
        "PayPayポイント,-,本人,04638686270424956930\r\n"
        "2025/02/10 12:55:55,257,-,-,-,-,-,支払い,キャンドゥ　横浜橋商店街,"
        "クレジット VISA 4575,-,本人,04638686270424956930\r\n"
    )
    csv_file = tmp_path / _COMPOUND_CSV_FILENAME
    csv_file.write_text(csv_content, encoding=AppConstants.ENCODING_UTF8)
    txs, failures = parse_csv(csv_file, _make_config(csv_file))
    assert failures == []
    assert len(txs) == 1
    assert txs[0].amount == 330
    assert txs[0].merchant == _COMPOUND_MERCHANT
    assert txs[0].transaction_id == _COMPOUND_TRANSACTION_ID


# TC-02-04: ポイント入金（giftee +120円）
def test_parse_incoming_payment() -> None:
    """TC-02-04: 入金取引（giftee +120円）が正しくパースされることを確認する。"""
    txs, failures = parse_csv(
        FIXTURE_DIR / _INPUT_CSV_FILENAME,
        _make_config(FIXTURE_DIR / _INPUT_CSV_FILENAME),
    )
    assert failures == []
    giftee = next(t for t in txs if t.transaction_id == _GIFTEE_TRANSACTION_ID)
    assert giftee.amount == 120
    assert giftee.direction == AppConstants.DIRECTION_IN
    assert giftee.merchant == _GIFTEE_MERCHANT


# TC-02-05: UTF-8 エンコーディング
def test_encoding_utf8() -> None:
    """TC-02-05: UTF-8 エンコードの CSV ファイルが正しく読み込まれることを確認する。"""
    txs, failures = parse_csv(
        FIXTURE_DIR / _INPUT_CSV_FILENAME,
        _make_config(FIXTURE_DIR / _INPUT_CSV_FILENAME),
    )
    assert failures == []
    assert len(txs) > 0
    assert any(t.merchant == _MOS_MERCHANT for t in txs)


# TC-02-06: Shift_JIS エンコーディング
def test_encoding_sjis() -> None:
    """TC-02-06: Shift_JIS エンコードの CSV ファイルが正しく読み込まれることを確認する。"""
    sjis_path = FIXTURE_DIR / _INPUT_SJIS_CSV_FILENAME
    if not sjis_path.exists():
        pytest.skip(
            f"{_INPUT_SJIS_CSV_FILENAME} が未生成（run scripts/make_sjis_fixture.py）",
        )
    txs, failures = parse_csv(sjis_path, _make_config(sjis_path))
    assert failures == []
    assert len(txs) > 0
    assert any(t.merchant == _MOS_MERCHANT for t in txs)


def test_encoding_utf8_bom(tmp_path: Path) -> None:
    """TC-02-07: UTF-8 BOM 付き CSV ファイルが正しく読み込まれることを確認する。"""
    csv_content = (
        "取引日,出金金額（円）,入金金額（円）,海外出金金額,通貨,変換レート（円）,"
        "利用国,取引内容,取引先,取引方法,支払い区分,利用者,取引番号\r\n"
        "2025/02/11 19:24:02,920,-,-,-,-,-,支払い,モスのネット注文,"
        "クレジット VISA 4575,-,本人,BOM001\r\n"
    )
    csv_file = tmp_path / _BOM_CSV_FILENAME
    csv_file.write_text(csv_content, encoding=AppConstants.ENCODING_UTF8_SIG)

    txs, failures = parse_csv(csv_file, _make_config(csv_file))

    assert failures == []
    assert len(txs) == 1
    assert txs[0].transaction_id == _BOM_TRANSACTION_ID
    assert txs[0].merchant == _MOS_MERCHANT


# 海外取引のメモ追記
def test_foreign_transaction_memo() -> None:
    """海外取引の memo に国・通貨情報が追記されることを確認する。"""
    txs, failures = parse_csv(
        FIXTURE_DIR / _INPUT_CSV_FILENAME,
        _make_config(FIXTURE_DIR / _INPUT_CSV_FILENAME),
    )
    assert failures == []
    google = next(t for t in txs if t.transaction_id == _GOOGLE_TRANSACTION_ID)
    assert _FOREIGN_MEMO_MARKER in google.memo
    assert _JPY_CURRENCY in google.memo


def test_parse_csv_collects_invalid_rows(tmp_path: Path) -> None:
    """正常行と不正行が混在していても正常行の処理が継続されることを確認する。"""
    csv_content = (
        "取引日,出金金額（円）,入金金額（円）,海外出金金額,通貨,変換レート（円）,"
        "利用国,取引内容,取引先,取引方法,支払い区分,利用者,取引番号\r\n"
        "2025/02/11 19:24:02,920,-,-,-,-,-,支払い,モスのネット注文,"
        "クレジット VISA 4575,-,本人,OK001\r\n"
        ",-,-,-,-,-,-,支払い,giftee,PayPayポイント,-,-,BAD001\r\n"
    )
    csv_file = tmp_path / _MIXED_CSV_FILENAME
    csv_file.write_text(csv_content, encoding=AppConstants.ENCODING_UTF8)

    txs, failures = parse_csv(csv_file, _make_config(csv_file))

    assert len(txs) == 1
    assert txs[0].transaction_id == _OK_TRANSACTION_ID
    assert len(failures) == 1
    assert failures[0].transaction_id == _BAD_TRANSACTION_ID
    assert failures[0].error_type == _PARSE_ERROR_INVALID_DATE
    assert failures[0].row_index == 3


def test_parse_csv_rejects_zero_amount_rows(tmp_path: Path) -> None:
    """TC-02-08: 出金額と入金額が両方0の行は ParseFailure として収集される。"""
    csv_content = (
        "取引日,出金金額（円）,入金金額（円）,海外出金金額,通貨,変換レート（円）,"
        "利用国,取引内容,取引先,取引方法,支払い区分,利用者,取引番号\r\n"
        "2025/02/11 19:24:02,-,-,-,-,-,-,支払い,ゼロ金額加盟店,"
        "PayPay残高,-,本人,ZERO001\r\n"
    )
    csv_file = tmp_path / "zero_amount.csv"
    csv_file.write_text(csv_content, encoding=AppConstants.ENCODING_UTF8)

    txs, failures = parse_csv(csv_file, _make_config(csv_file))

    assert txs == []
    assert len(failures) == 1
    assert failures[0].transaction_id == "ZERO001"
    assert failures[0].error_type == _PARSE_ERROR_INVALID_VALUE
    assert failures[0].row_index == 2


def test_parse_csv_rejects_ambiguous_amount_rows(tmp_path: Path) -> None:
    """TC-02-09: 出金額と入金額が両方正数の行は ParseFailure として収集される。"""
    csv_content = (
        "取引日,出金金額（円）,入金金額（円）,海外出金金額,通貨,変換レート（円）,"
        "利用国,取引内容,取引先,取引方法,支払い区分,利用者,取引番号\r\n"
        "2025/02/11 19:24:02,100,200,-,-,-,-,支払い,曖昧金額加盟店,"
        "PayPay残高,-,本人,AMB001\r\n"
    )
    csv_file = tmp_path / "ambiguous_amount.csv"
    csv_file.write_text(csv_content, encoding=AppConstants.ENCODING_UTF8)

    txs, failures = parse_csv(csv_file, _make_config(csv_file))

    assert txs == []
    assert len(failures) == 1
    assert failures[0].transaction_id == "AMB001"
    assert failures[0].error_type == _PARSE_ERROR_INVALID_VALUE
    assert failures[0].row_index == 2


def test_parse_csv_bom_preserves_row_index_for_invalid_rows(tmp_path: Path) -> None:
    """BOM 付き UTF-8 でも ParseFailure の row_index が物理行番号を維持することを確認する。"""
    csv_content = (
        "取引日,出金金額（円）,入金金額（円）,海外出金金額,通貨,変換レート（円）,"
        "利用国,取引内容,取引先,取引方法,支払い区分,利用者,取引番号\r\n"
        "2025/02/11 19:24:02,920,-,-,-,-,-,支払い,モスのネット注文,"
        "クレジット VISA 4575,-,本人,OK001\r\n"
        ",-,-,-,-,-,-,支払い,giftee,PayPayポイント,-,-,BAD001\r\n"
    )
    csv_file = tmp_path / _MIXED_BOM_CSV_FILENAME
    csv_file.write_text(csv_content, encoding=AppConstants.ENCODING_UTF8_SIG)

    txs, failures = parse_csv(csv_file, _make_config(csv_file))

    assert len(txs) == 1
    assert txs[0].transaction_id == _OK_TRANSACTION_ID
    assert len(failures) == 1
    assert failures[0].transaction_id == _BAD_TRANSACTION_ID
    assert failures[0].row_index == 3


def test_parse_csv_collects_missing_column(tmp_path: Path) -> None:
    """必須列が欠損している場合に ParseFailure として収集されることを確認する。"""
    csv_content = (
        "出金金額（円）,入金金額（円）,海外出金金額,通貨,変換レート（円）,"
        "利用国,取引内容,取引先,取引方法,支払い区分,利用者,取引番号\r\n"
        "920,-,-,-,-,-,支払い,モスのネット注文,クレジット VISA 4575,-,本人,OK001\r\n"
    )
    csv_file = tmp_path / _MISSING_COLUMN_CSV_FILENAME
    csv_file.write_text(csv_content, encoding=AppConstants.ENCODING_UTF8)

    txs, failures = parse_csv(csv_file, _make_config(csv_file))

    assert txs == []
    assert len(failures) == 1
    assert failures[0].error_type == _PARSE_ERROR_MISSING_COLUMN
    assert _TRADE_DATE_COLUMN in failures[0].error_message


# _merge_compound 直接テスト（取引番号なし行のパススルー）
def test_merge_compound_no_id() -> None:
    """取引番号が空の行が _merge_compound で集約されずにそのまま通過することを確認する。"""
    rows = [
        (
            2,
            {
                "取引番号": "",
                "出金金額（円）": "100",
                "入金金額（円）": AppConstants.HYPHEN,
            },
        ),
        (
            3,
            {
                "取引番号": "",
                "出金金額（円）": "200",
                "入金金額（円）": AppConstants.HYPHEN,
            },
        ),
    ]
    result = _merge_compound(rows)
    assert len(result) == 2
