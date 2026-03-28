"""filter モジュールのテスト。

対応テストケース:
    TC-03-01: PPCD_A_ プレフィックスの除外
    TC-03-02: 除外されない取引
    TC-03-03: カスタム exclude_prefixes
"""

from __future__ import annotations

from datetime import datetime

from src.filter import apply_exclude, apply_mapping
from src.models import MappingRule, Transaction


def _make_tx(
    transaction_id: str | None = "TX001",
    merchant: str = "テスト商店",
    amount: int = 100,
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
        direction="out",
        memo="支払い",
        merchant=merchant,
        transaction_id=transaction_id,
    )


# TC-03-01: PPCD_A_ プレフィックスの除外
def test_exclude_ppcd_a() -> None:
    """
    TC-03-01: PPCD_A_ プレフィックスの取引が除外リストに振り分けられることを確認する。
    """
    txs = [
        _make_tx(transaction_id="PPCD_A_12345"),
        _make_tx(transaction_id="04639628474580213761"),
    ]
    passed, excluded = apply_exclude(txs, ["PPCD_A_"])
    assert len(passed) == 1
    assert len(excluded) == 1
    assert excluded[0].transaction_id == "PPCD_A_12345"


# TC-03-02: 除外されない取引
def test_not_excluded() -> None:
    """TC-03-02: PPCD_A_ に合致しない取引が除外されないことを確認する。"""
    txs = [_make_tx(transaction_id="04639628474580213761")]
    passed, excluded = apply_exclude(txs, ["PPCD_A_"])
    assert len(passed) == 1
    assert len(excluded) == 0


# TC-03-03: カスタム exclude_prefixes
def test_custom_prefix() -> None:
    """TC-03-03: カスタムの exclude_prefixes が正しく適用されることを確認する。"""
    txs = [
        _make_tx(transaction_id="TEST_001"),
        _make_tx(transaction_id="PPCD_A_999"),
        _make_tx(transaction_id="NORMAL_001"),
    ]
    passed, excluded = apply_exclude(txs, ["PPCD_A_", "TEST_"])
    assert len(passed) == 1
    assert passed[0].transaction_id == "NORMAL_001"
    assert len(excluded) == 2


# 取引番号 None の行は除外されない
def test_no_transaction_id_not_excluded() -> None:
    """取引番号が None の行は除外対象プレフィックスに合致しないことを確認する。"""
    txs = [_make_tx(transaction_id=None)]
    passed, excluded = apply_exclude(txs, ["PPCD_A_"])
    assert len(passed) == 1
    assert len(excluded) == 0


# マッピング: contains
def test_mapping_contains() -> None:
    """contains モードのマッピングルールが merchant の部分一致で適用されることを確認する。"""
    txs = [_make_tx(merchant="ファミリーマート - 弘明寺中里")]
    rules = [MappingRule(keyword="ファミリーマート", category="コンビニ")]
    result = apply_mapping(txs, rules)
    assert result[0].category == "コンビニ"


# マッピング: starts_with
def test_mapping_starts_with() -> None:
    """starts_with モードのマッピングルールが merchant の前方一致で適用されることを確認する。"""
    txs = [_make_tx(merchant="セブンイレブン横浜")]
    rules = [
        MappingRule(keyword="セブン", category="コンビニ", match_mode="starts_with"),
    ]
    result = apply_mapping(txs, rules)
    assert result[0].category == "コンビニ"


# マッピング: regex
def test_mapping_regex() -> None:
    """regex モードのマッピングルールが merchant の正規表現マッチで適用されることを確認する。"""
    txs = [_make_tx(merchant="Google - GOOGLE PLAY JAPAN")]
    rules = [
        MappingRule(
            keyword=r"Google.*PLAY",
            category="サブスクリプション",
            match_mode="regex",
        ),
    ]
    result = apply_mapping(txs, rules)
    assert result[0].category == "サブスクリプション"


# マッピング: priority（高いほど優先）
def test_mapping_priority() -> None:
    """priority の高いルールが先に評価されることを確認する。"""
    txs = [_make_tx(merchant="セブン - イレブン")]
    rules = [
        MappingRule(keyword="セブン", category="コンビニ", priority=100),
        MappingRule(keyword="セブン - イレブン", category="食料品", priority=200),
    ]
    result = apply_mapping(txs, rules)
    assert result[0].category == "食料品"


# マッピング: ルールなし → 未分類
def test_mapping_no_match() -> None:
    """いずれのルールにもマッチしない場合に category が "未分類" のままであることを確認する。"""
    txs = [_make_tx(merchant="謎の商店")]
    rules = [MappingRule(keyword="ファミリーマート", category="コンビニ")]
    result = apply_mapping(txs, rules)
    assert result[0].category == "未分類"


# ルールなし（空リスト）→ 未分類
def test_mapping_empty_rules() -> None:
    """ルールリストが空の場合に category が "未分類" のままであることを確認する。"""
    txs = [_make_tx(merchant="何でも屋")]
    result = apply_mapping(txs, [])
    assert result[0].category == "未分類"
