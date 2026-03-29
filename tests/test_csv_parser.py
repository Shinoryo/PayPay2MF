"""csv_parser モジュールのテスト。

対応テストケース:
    TC-02-01: 通常の支払い取引のパース
    TC-02-02: カンマを含む金額文字列の数値化
    TC-02-03: 複合支払い（同一取引番号の複数行）の集約
    TC-02-04: ポイント入金のパース
    TC-02-05: UTF-8 エンコーディング
    TC-02-06: Shift_JIS エンコーディング
    TC-02-07: BOM 付き UTF-8 エンコーディング
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.csv_parser import _merge_compound, _parse_amount, parse_csv
from src.models import AppConfig


def _make_config(csv_path: Path) -> AppConfig:
    """テスト用の AppConfig を生成する。

    Args:
        csv_path: input_csv に設定するパス。

    Returns:
        テスト用 AppConfig インスタンス。
    """
    return AppConfig(
        chrome_user_data_dir="C:\\dummy",
        chrome_profile="Default",
        dry_run=True,
        input_csv=csv_path,
        mf_account="PayPay残高",
    )


FIXTURE_DIR = Path(__file__).parent / "fixtures"


# TC-02-01: 通常支払（モス 920円）
def test_parse_normal_payment() -> None:
    """TC-02-01: 通常の支払い取引（モス 920円）が正しくパースされることを確認する。"""
    txs, failures = parse_csv(
        FIXTURE_DIR / "test_input.csv",
        _make_config(FIXTURE_DIR / "test_input.csv"),
    )
    assert failures == []
    mos = next(t for t in txs if t.transaction_id == "04639628474580213761")
    assert mos.date == datetime(2025, 2, 11, 19, 24, 2)  # noqa: DTZ001
    assert mos.amount == 920
    assert mos.direction == "out"
    assert mos.merchant == "モスのネット注文"


# TC-02-02: カンマ含む金額文字列の数値化
def test_parse_amount_with_comma() -> None:
    """TC-02-02: カンマを含む金額文字列が整数に正しく変換されることを確認する。"""
    assert _parse_amount('"1,280"') == 1280
    assert _parse_amount("1,280") == 1280
    assert _parse_amount("-") == 0
    assert _parse_amount("") == 0
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
    csv_file = tmp_path / "compound.csv"
    csv_file.write_text(csv_content, encoding="utf-8")
    txs, failures = parse_csv(csv_file, _make_config(csv_file))
    assert failures == []
    assert len(txs) == 1
    assert txs[0].amount == 330
    assert txs[0].merchant == "キャンドゥ　横浜橋商店街"
    assert txs[0].transaction_id == "04638686270424956930"


# TC-02-04: ポイント入金（giftee +120円）
def test_parse_incoming_payment() -> None:
    """TC-02-04: 入金取引（giftee +120円）が正しくパースされることを確認する。"""
    txs, failures = parse_csv(
        FIXTURE_DIR / "test_input.csv",
        _make_config(FIXTURE_DIR / "test_input.csv"),
    )
    assert failures == []
    giftee = next(
        t for t in txs if t.transaction_id == "856574761326657536-a0196d18"
    )
    assert giftee.amount == 120
    assert giftee.direction == "in"
    assert giftee.merchant == "giftee"


# TC-02-05: UTF-8 エンコーディング
def test_encoding_utf8() -> None:
    """TC-02-05: UTF-8 エンコードの CSV ファイルが正しく読み込まれることを確認する。"""
    txs, failures = parse_csv(
        FIXTURE_DIR / "test_input.csv",
        _make_config(FIXTURE_DIR / "test_input.csv"),
    )
    assert failures == []
    assert len(txs) > 0
    assert any(t.merchant == "モスのネット注文" for t in txs)


# TC-02-06: Shift_JIS エンコーディング
def test_encoding_sjis() -> None:
    """TC-02-06: Shift_JIS エンコードの CSV ファイルが正しく読み込まれることを確認する。"""
    sjis_path = FIXTURE_DIR / "test_input_sjis.csv"
    if not sjis_path.exists():
        pytest.skip("test_input_sjis.csv が未生成（run scripts/make_sjis_fixture.py）")
    txs, failures = parse_csv(sjis_path, _make_config(sjis_path))
    assert failures == []
    assert len(txs) > 0
    assert any(t.merchant == "モスのネット注文" for t in txs)


def test_encoding_utf8_bom(tmp_path: Path) -> None:
    """TC-02-07: UTF-8 BOM 付き CSV ファイルが正しく読み込まれることを確認する。"""
    csv_content = (
        "取引日,出金金額（円）,入金金額（円）,海外出金金額,通貨,変換レート（円）,"
        "利用国,取引内容,取引先,取引方法,支払い区分,利用者,取引番号\r\n"
        "2025/02/11 19:24:02,920,-,-,-,-,-,支払い,モスのネット注文,"
        "クレジット VISA 4575,-,本人,BOM001\r\n"
    )
    csv_file = tmp_path / "bom.csv"
    csv_file.write_text(csv_content, encoding="utf-8-sig")

    txs, failures = parse_csv(csv_file, _make_config(csv_file))

    assert failures == []
    assert len(txs) == 1
    assert txs[0].transaction_id == "BOM001"
    assert txs[0].merchant == "モスのネット注文"


# 海外取引のメモ追記
def test_foreign_transaction_memo() -> None:
    """海外取引の memo に国・通貨情報が追記されることを確認する。"""
    txs, failures = parse_csv(
        FIXTURE_DIR / "test_input.csv",
        _make_config(FIXTURE_DIR / "test_input.csv"),
    )
    assert failures == []
    google = next(
        t for t in txs if t.transaction_id == "PPCD_A_2025021122321300218846"
    )
    assert "海外" in google.memo
    assert "JPY" in google.memo


def test_parse_csv_collects_invalid_rows(tmp_path: Path) -> None:
    """正常行と不正行が混在していても正常行の処理が継続されることを確認する。"""
    csv_content = (
        "取引日,出金金額（円）,入金金額（円）,海外出金金額,通貨,変換レート（円）,"
        "利用国,取引内容,取引先,取引方法,支払い区分,利用者,取引番号\r\n"
        "2025/02/11 19:24:02,920,-,-,-,-,-,支払い,モスのネット注文,"
        "クレジット VISA 4575,-,本人,OK001\r\n"
        ",-,-,-,-,-,-,支払い,giftee,PayPayポイント,-,-,BAD001\r\n"
    )
    csv_file = tmp_path / "mixed.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    txs, failures = parse_csv(csv_file, _make_config(csv_file))

    assert len(txs) == 1
    assert txs[0].transaction_id == "OK001"
    assert len(failures) == 1
    assert failures[0].transaction_id == "BAD001"
    assert failures[0].error_type == "invalid_date"
    assert failures[0].row_index == 3


def test_parse_csv_bom_preserves_row_index_for_invalid_rows(tmp_path: Path) -> None:
    """BOM 付き UTF-8 でも ParseFailure の row_index が物理行番号を維持することを確認する。"""
    csv_content = (
        "取引日,出金金額（円）,入金金額（円）,海外出金金額,通貨,変換レート（円）,"
        "利用国,取引内容,取引先,取引方法,支払い区分,利用者,取引番号\r\n"
        "2025/02/11 19:24:02,920,-,-,-,-,-,支払い,モスのネット注文,"
        "クレジット VISA 4575,-,本人,OK001\r\n"
        ",-,-,-,-,-,-,支払い,giftee,PayPayポイント,-,-,BAD001\r\n"
    )
    csv_file = tmp_path / "mixed_bom.csv"
    csv_file.write_text(csv_content, encoding="utf-8-sig")

    txs, failures = parse_csv(csv_file, _make_config(csv_file))

    assert len(txs) == 1
    assert txs[0].transaction_id == "OK001"
    assert len(failures) == 1
    assert failures[0].transaction_id == "BAD001"
    assert failures[0].row_index == 3


def test_parse_csv_collects_missing_column(tmp_path: Path) -> None:
    """必須列が欠損している場合に ParseFailure として収集されることを確認する。"""
    csv_content = (
        "出金金額（円）,入金金額（円）,海外出金金額,通貨,変換レート（円）,"
        "利用国,取引内容,取引先,取引方法,支払い区分,利用者,取引番号\r\n"
        "920,-,-,-,-,-,支払い,モスのネット注文,クレジット VISA 4575,-,本人,OK001\r\n"
    )
    csv_file = tmp_path / "missing_column.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    txs, failures = parse_csv(csv_file, _make_config(csv_file))

    assert txs == []
    assert len(failures) == 1
    assert failures[0].error_type == "missing_column"
    assert "取引日" in failures[0].error_message


# _merge_compound 直接テスト（取引番号なし行のパススルー）
def test_merge_compound_no_id() -> None:
    """取引番号が空の行が _merge_compound で集約されずにそのまま通過することを確認する。"""
    rows = [
        (
            2,
            {
                "取引番号": "",
                "出金金額（円）": "100",
                "入金金額（円）": "-",
            },
        ),
        (
            3,
            {
                "取引番号": "",
                "出金金額（円）": "200",
                "入金金額（円）": "-",
            },
        ),
    ]
    result = _merge_compound(rows)
    assert len(result) == 2
