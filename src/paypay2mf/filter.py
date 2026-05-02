"""除外フィルタとカテゴリマッピングの適用。

取引番号プレフィックスによる除外と、キーワードマッチングによる
カテゴリ自動割り当て機能を提供する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from paypay2mf.constants import AppConstants

if TYPE_CHECKING:
    from paypay2mf.models import MappingRule, Transaction


@dataclass(frozen=True, slots=True)
class _PreparedRule:
    category: str
    keyword: str
    match_mode: str
    direction: str
    compiled_pattern: re.Pattern[str] | None = None


_RULE_TO_TX_DIRECTION = {
    AppConstants.RULE_DIRECTION_INCOME: AppConstants.DIRECTION_IN,
    AppConstants.RULE_DIRECTION_EXPENSE: AppConstants.DIRECTION_OUT,
}


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

    各 Transaction に対して rules を優先順で評価し、最初にマッチした
    カテゴリを設定する。評価順は以下のとおり。

    1. priority 降順（数値が大きいほど優先）
    2. 同一 priority では direction 指定（income/expense）を any より優先

    direction が income/expense のルールは、Transaction.direction が
    対応する in/out の場合にのみマッチ候補となる。
    マッチしない場合は category は "未分類" のまま。

    Args:
        records: マッピング対象の Transaction のリスト。
        rules: カテゴリマッピングルールのリスト。

    Returns:
        カテゴリが更新された Transaction のリスト。
    """
    prepared_rules = _prepare_rules(rules)

    result: list[Transaction] = []
    for tx in records:
        tx.category = _match_category(tx, prepared_rules)
        result.append(tx)

    return result


def _prepare_rules(rules: list[MappingRule]) -> list[_PreparedRule]:
    prepared: list[_PreparedRule] = []
    for rule in sorted(
        rules,
        key=lambda r: (
            -r.priority,
            r.direction == AppConstants.RULE_DIRECTION_ANY,
        ),
    ):
        compiled_pattern = None
        if rule.match_mode == AppConstants.MATCH_MODE_REGEX:
            compiled_pattern = re.compile(rule.keyword)
        prepared.append(
            _PreparedRule(
                category=rule.category,
                keyword=rule.keyword,
                match_mode=rule.match_mode,
                direction=rule.direction,
                compiled_pattern=compiled_pattern,
            )
        )
    return prepared


def _match_category(
    tx: Transaction,
    prepared_rules: list[_PreparedRule],
) -> str:
    """Transaction に対してルールを評価し、最初にマッチしたカテゴリ名を返す。

    Args:
        tx: 評価対象の取引データ。
        prepared_rules: カテゴリマッピングルールのリスト。priority 降順を想定。

    Returns:
        マッチしたカテゴリ名。マッチしない場合は "未分類"。
    """
    for rule in prepared_rules:
        if _matches(tx, rule):
            return rule.category
    return AppConstants.DEFAULT_CATEGORY


def _matches(tx: Transaction, rule: _PreparedRule) -> bool:
    """単一のルールが Transaction にマッチするか判定する。

    Args:
        tx: 評価対象の取引データ。
        rule: 評価するマッピングルール。

    Returns:
        マッチすれば True、しなければ False。
    """
    if rule.direction != AppConstants.RULE_DIRECTION_ANY:
        expected_direction = _RULE_TO_TX_DIRECTION.get(rule.direction)
        if tx.direction != expected_direction:
            return False

    merchant = tx.merchant
    if rule.match_mode == AppConstants.MATCH_MODE_CONTAINS:
        return rule.keyword in merchant
    if rule.match_mode == AppConstants.MATCH_MODE_STARTS_WITH:
        return merchant.startswith(rule.keyword)
    if rule.match_mode == AppConstants.MATCH_MODE_REGEX:
        return bool(rule.compiled_pattern and rule.compiled_pattern.search(merchant))
    return False
