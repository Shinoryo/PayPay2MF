"""filter モジュールのテスト。

対応テストケース:
    TC-03-01: PPCD_A_ プレフィックスの除外
    TC-03-02: 除外されない取引
    TC-03-03: カスタム exclude_prefixes
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

from paypay2mf.constants import AppConstants
from paypay2mf.filter import apply_exclude, apply_mapping
from paypay2mf.models import MappingRule, Transaction

_DEFAULT_TRANSACTION_ID = "TX001"
_DEFAULT_MERCHANT = "テスト商店"
_DEFAULT_MEMO = "支払い"
_PAYPAY_CARD_TRANSACTION_ID = "PPCD_A_12345"
_PAYPAY_CARD_OTHER_ID = "PPCD_A_999"
_NORMAL_TRANSACTION_ID = "04639628474580213761"
_TEST_PREFIX_TRANSACTION_ID = "TEST_001"
_NORMAL_PREFIX_TRANSACTION_ID = "NORMAL_001"
_FAMILY_MART = "ファミリーマート"
_CONVENIENCE_STORE = "コンビニ"
_SUBSCRIPTION = "サブスクリプション"
_SEVEN = "セブン"
_SEVEN_ELEVEN = "セブン - イレブン"
_GROCERY = "食料品"
_CUSTOM_PREFIX = "TEST_"


def _make_tx(
    transaction_id: str | None = _DEFAULT_TRANSACTION_ID,
    merchant: str = _DEFAULT_MERCHANT,
    amount: int = 100,
    direction: str = AppConstants.DIRECTION_OUT,
) -> Transaction:
    """テスト用の Transaction を生成する。

    Args:
        transaction_id: 取引番号。デフォルトは "TX001"。
        merchant: 取引先名。デフォルトは "テスト商店"。
        amount: 金額。デフォルトは 100。

    Returns:
        テスト用 Transaction インスタンス。
    """
    return Transaction(
        date=datetime(2025, 1, 1),  # noqa: DTZ001
        amount=amount,
        direction=direction,
        memo=_DEFAULT_MEMO,
        merchant=merchant,
        transaction_id=transaction_id,
    )


# TC-03-01: PPCD_A_ プレフィックスの除外
def test_exclude_ppcd_a() -> None:
    """
    TC-03-01: PPCD_A_ プレフィックスの取引が除外リストに振り分けられることを確認する。
    """
    txs = [
        _make_tx(transaction_id=_PAYPAY_CARD_TRANSACTION_ID),
        _make_tx(transaction_id=_NORMAL_TRANSACTION_ID),
    ]
    passed, excluded = apply_exclude(txs, [AppConstants.EXCLUDE_PREFIX_PAYPAY_CARD])
    assert len(passed) == 1
    assert len(excluded) == 1
    assert excluded[0].transaction_id == _PAYPAY_CARD_TRANSACTION_ID


# TC-03-02: 除外されない取引
def test_not_excluded() -> None:
    """TC-03-02: PPCD_A_ に合致しない取引が除外されないことを確認する。"""
    txs = [_make_tx(transaction_id=_NORMAL_TRANSACTION_ID)]
    passed, excluded = apply_exclude(txs, [AppConstants.EXCLUDE_PREFIX_PAYPAY_CARD])
    assert len(passed) == 1
    assert len(excluded) == 0


# TC-03-03: カスタム exclude_prefixes
def test_custom_prefix() -> None:
    """TC-03-03: カスタムの exclude_prefixes が正しく適用されることを確認する。"""
    txs = [
        _make_tx(transaction_id=_TEST_PREFIX_TRANSACTION_ID),
        _make_tx(transaction_id=_PAYPAY_CARD_OTHER_ID),
        _make_tx(transaction_id=_NORMAL_PREFIX_TRANSACTION_ID),
    ]
    passed, excluded = apply_exclude(
        txs,
        [AppConstants.EXCLUDE_PREFIX_PAYPAY_CARD, _CUSTOM_PREFIX],
    )
    assert len(passed) == 1
    assert passed[0].transaction_id == _NORMAL_PREFIX_TRANSACTION_ID
    assert len(excluded) == 2


# 取引番号 None の行は除外されない
def test_no_transaction_id_not_excluded() -> None:
    """取引番号が None の行は除外対象プレフィックスに合致しないことを確認する。"""
    txs = [_make_tx(transaction_id=None)]
    passed, excluded = apply_exclude(txs, [AppConstants.EXCLUDE_PREFIX_PAYPAY_CARD])
    assert len(passed) == 1
    assert len(excluded) == 0


# マッピング: contains
def test_mapping_contains() -> None:
    """contains モードのマッピングルールが merchant の部分一致で適用されることを確認する。"""
    txs = [_make_tx(merchant="ファミリーマート - 弘明寺中里")]
    rules = [MappingRule(keyword=_FAMILY_MART, category=_CONVENIENCE_STORE)]
    result = apply_mapping(txs, rules)
    assert result[0].category == _CONVENIENCE_STORE


# マッピング: starts_with
def test_mapping_starts_with() -> None:
    """starts_with モードのマッピングルールが merchant の前方一致で適用されることを確認する。"""
    txs = [_make_tx(merchant="セブンイレブン横浜")]
    rules = [
        MappingRule(
            keyword=_SEVEN,
            category=_CONVENIENCE_STORE,
            match_mode=AppConstants.MATCH_MODE_STARTS_WITH,
        ),
    ]
    result = apply_mapping(txs, rules)
    assert result[0].category == _CONVENIENCE_STORE


# マッピング: regex
def test_mapping_regex() -> None:
    """regex モードのマッピングルールが merchant の正規表現マッチで適用されることを確認する。"""
    txs = [_make_tx(merchant="Google - GOOGLE PLAY JAPAN")]
    rules = [
        MappingRule(
            keyword=r"Google.*PLAY",
            category=_SUBSCRIPTION,
            match_mode=AppConstants.MATCH_MODE_REGEX,
        ),
    ]
    result = apply_mapping(txs, rules)
    assert result[0].category == _SUBSCRIPTION


def test_mapping_contains_preserves_keyword_surrounding_whitespace() -> None:
    """contains モードでは keyword の前後空白がマッチ条件として保持されることを確認する。"""
    txs = [_make_tx(merchant="セブン-イレブン")]
    rules = [
        MappingRule(
            keyword=" セブン ",
            category=_CONVENIENCE_STORE,
            match_mode=AppConstants.MATCH_MODE_CONTAINS,
        ),
    ]

    result = apply_mapping(txs, rules)

    assert result[0].category == AppConstants.DEFAULT_CATEGORY


def test_mapping_starts_with_preserves_keyword_surrounding_whitespace() -> None:
    """starts_with モードでは keyword の前後空白がマッチ条件として保持されることを確認する。"""
    txs = [_make_tx(merchant="セブンイレブン横浜")]
    rules = [
        MappingRule(
            keyword=" セブン",
            category=_CONVENIENCE_STORE,
            match_mode=AppConstants.MATCH_MODE_STARTS_WITH,
        ),
    ]

    result = apply_mapping(txs, rules)

    assert result[0].category == AppConstants.DEFAULT_CATEGORY


def test_mapping_regex_preserves_keyword_surrounding_whitespace() -> None:
    """regex モードでは keyword の前後空白を含むパターンがそのまま評価されることを確認する。"""
    txs = [_make_tx(merchant="セブンイレブン横浜")]
    rules = [
        MappingRule(
            keyword=r" ^セブン",
            category=_CONVENIENCE_STORE,
            match_mode=AppConstants.MATCH_MODE_REGEX,
        ),
    ]

    result = apply_mapping(txs, rules)

    assert result[0].category == AppConstants.DEFAULT_CATEGORY


def test_mapping_regex_compiles_each_rule_once(monkeypatch) -> None:
    """regex ルールは apply_mapping ごとに 1 回だけ compile されることを確認する。"""
    compile_mock = Mock(wraps=__import__("re").compile)
    monkeypatch.setattr("paypay2mf.filter.re.compile", compile_mock)

    txs = [_make_tx(merchant="Google - GOOGLE PLAY JAPAN")]
    rules = [
        MappingRule(
            keyword=r"Google.*PLAY",
            category=_SUBSCRIPTION,
            match_mode=AppConstants.MATCH_MODE_REGEX,
        ),
    ]

    result = apply_mapping(txs, rules)

    assert result[0].category == _SUBSCRIPTION
    compile_mock.assert_called_once_with(r"Google.*PLAY")


# マッピング: priority（高いほど優先）
def test_mapping_priority() -> None:
    """priority の高いルールが先に評価されることを確認する。"""
    txs = [_make_tx(merchant="セブン - イレブン")]
    rules = [
        MappingRule(keyword=_SEVEN, category=_CONVENIENCE_STORE, priority=100),
        MappingRule(keyword=_SEVEN_ELEVEN, category=_GROCERY, priority=200),
    ]
    result = apply_mapping(txs, rules)
    assert result[0].category == _GROCERY


def test_mapping_direction_expense_matches_outgoing_only() -> None:
    """direction=expense ルールは出金取引にのみ適用されることを確認する。"""
    out_tx = _make_tx(
        merchant="セブン - イレブン", direction=AppConstants.DIRECTION_OUT
    )
    in_tx = _make_tx(merchant="セブン - イレブン", direction=AppConstants.DIRECTION_IN)
    rules = [
        MappingRule(
            keyword=_SEVEN_ELEVEN,
            category=_GROCERY,
            direction=AppConstants.RULE_DIRECTION_EXPENSE,
        )
    ]

    out_result = apply_mapping([out_tx], rules)
    in_result = apply_mapping([in_tx], rules)

    assert out_result[0].category == _GROCERY
    assert in_result[0].category == AppConstants.DEFAULT_CATEGORY


def test_mapping_direction_income_matches_incoming_only() -> None:
    """direction=income ルールは入金取引にのみ適用されることを確認する。"""
    out_tx = _make_tx(merchant="giftee", direction=AppConstants.DIRECTION_OUT)
    in_tx = _make_tx(merchant="giftee", direction=AppConstants.DIRECTION_IN)
    rules = [
        MappingRule(
            keyword="giftee",
            category="一時所得",
            direction=AppConstants.RULE_DIRECTION_INCOME,
        )
    ]

    out_result = apply_mapping([out_tx], rules)
    in_result = apply_mapping([in_tx], rules)

    assert out_result[0].category == AppConstants.DEFAULT_CATEGORY
    assert in_result[0].category == "一時所得"


def test_mapping_direction_any_matches_both_directions() -> None:
    """direction=any ルールは入出金の両方に適用されることを確認する。"""
    out_tx = _make_tx(
        merchant="セブン - イレブン", direction=AppConstants.DIRECTION_OUT
    )
    in_tx = _make_tx(merchant="セブン - イレブン", direction=AppConstants.DIRECTION_IN)
    rules = [
        MappingRule(
            keyword=_SEVEN_ELEVEN,
            category=_GROCERY,
            direction=AppConstants.RULE_DIRECTION_ANY,
        )
    ]

    out_result = apply_mapping([out_tx], rules)
    in_result = apply_mapping([in_tx], rules)

    assert out_result[0].category == _GROCERY
    assert in_result[0].category == _GROCERY


def test_mapping_direction_specific_rule_prioritized_over_any() -> None:
    """同一priorityなら direction 指定ルールが any より優先されることを確認する。"""
    tx = _make_tx(merchant="セブン - イレブン", direction=AppConstants.DIRECTION_OUT)
    rules = [
        MappingRule(
            keyword=_SEVEN_ELEVEN,
            category="候補-any",
            direction=AppConstants.RULE_DIRECTION_ANY,
            priority=320,
        ),
        MappingRule(
            keyword=_SEVEN_ELEVEN,
            category="候補-expense",
            direction=AppConstants.RULE_DIRECTION_EXPENSE,
            priority=320,
        ),
    ]

    result = apply_mapping([tx], rules)

    assert result[0].category == "候補-expense"


# マッピング: ルールなし → 未分類
def test_mapping_no_match() -> None:
    """いずれのルールにもマッチしない場合に category が "未分類" のままであることを確認する。"""
    txs = [_make_tx(merchant="謎の商店")]
    rules = [MappingRule(keyword=_FAMILY_MART, category=_CONVENIENCE_STORE)]
    result = apply_mapping(txs, rules)
    assert result[0].category == AppConstants.DEFAULT_CATEGORY


# ルールなし（空リスト）→ 未分類
def test_mapping_empty_rules() -> None:
    """ルールリストが空の場合に category が "未分類" のままであることを確認する。"""
    txs = [_make_tx(merchant="何でも屋")]
    result = apply_mapping(txs, [])
    assert result[0].category == AppConstants.DEFAULT_CATEGORY
