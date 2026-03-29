"""除外フィルタとカテゴリマッピングの適用。

取引番号プレフィックスによる除外と、キーワードマッチングによる
カテゴリ自動割り当て機能を提供する。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.constants import AppConstants

if TYPE_CHECKING:
    from src.models import MappingRule, Transaction


def apply_exclude(
    records: list[Transaction],
    prefixes: list[str],
) -> tuple[list[Transaction], list[Transaction]]:
    """除外プレフィックスに合致する取引を振り分ける。

    取引番号がいずれかの prefix で始まる取引を除外リストに移す。
    取引番号が None の行は常に通過させる。

    Args:
        records: フィルタ前の Transaction のリスト。
        prefixes: 除外対象の取引番号プレフィックスのリスト。

    Returns:
        （通過した取引のリスト、除外された取引のリスト）のタプル。
    """
    passed: list[Transaction] = []
    excluded: list[Transaction] = []

    for tx in records:
        tid = tx.transaction_id or AppConstants.EMPTY_STRING
        if any(tid.startswith(p) for p in prefixes):
            excluded.append(tx)
        else:
            passed.append(tx)

    return passed, excluded


def apply_mapping(
    records: list[Transaction],
    rules: list[MappingRule],
) -> list[Transaction]:
    """カテゴリマッピングルールを適用してカテゴリを更新する。

    各 Transaction の merchant に対して rules を priority 降順で評価し、
    最初にマッチしたカテゴリを設定する。マッチしない場合は "未分類" のまま。

    Args:
        records: マッピング対象の Transaction のリスト。
        rules: カテゴリマッピングルールのリスト。

    Returns:
        カテゴリが更新された Transaction のリスト。
    """
    sorted_rules = sorted(rules, key=lambda r: r.priority, reverse=True)

    result: list[Transaction] = []
    for tx in records:
        tx.category = _match_category(tx.merchant, sorted_rules)
        result.append(tx)

    return result


def _match_category(
    merchant: str, sorted_rules: list[MappingRule],
) -> str:
    """merchant に対してルールを評価し、最初にマッチしたカテゴリ名を返す。

    Args:
        merchant: 取引先名。
        sorted_rules: カテゴリマッピングルールのリスト。priority 降順を想定。

    Returns:
        マッチしたカテゴリ名。マッチしない場合は "未分類"。
    """
    for rule in sorted_rules:
        if _matches(merchant, rule):
            return rule.category
    return AppConstants.DEFAULT_CATEGORY


def _matches(merchant: str, rule: MappingRule) -> bool:
    """単一のルールが merchant にマッチするか判定する。

    Args:
        merchant: 取引先名。
        rule: 評価するマッピングルール。

    Returns:
        マッチすれば True、しなければ False。
    """
    if rule.match_mode == AppConstants.MATCH_MODE_CONTAINS:
        return rule.keyword in merchant
    if rule.match_mode == AppConstants.MATCH_MODE_STARTS_WITH:
        return merchant.startswith(rule.keyword)
    if rule.match_mode == AppConstants.MATCH_MODE_REGEX:
        return bool(re.search(rule.keyword, merchant))
    return False
