"""PayPay CSV ファイルのパース処理。

PayPay の利用明細 CSV を読み込み、Transaction オブジェクトのリストに変換する。
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from src.models import AppConfig, Transaction

# UTF8 BOM
_UTF8_BOM = "\ufeff"

# エラーメッセージ定数
_ERR_UNSUPPORTED_ENCODING = "対応するエンコーディングで読み込めません: {}"
_ERR_DATE_PARSE_FAILED = "日付のパースに失敗しました: {!r}"

# 列名の定数
_COL_TRADE_DATE = "取引日"
_COL_OUT_AMOUNT = "出金金額（円）"
_COL_IN_AMOUNT = "入金金額（円）"
_COL_FOREIGN = "海外出金金額"
_COL_CURRENCY = "通貨"
_COL_RATE = "変換レート（円）"
_COL_COUNTRY = "利用国"
_COL_CONTENT = "取引内容"
_COL_MERCHANT = "取引先"
_COL_METHOD = "取引方法"
_COL_PAYMENT_TYPE = "支払い区分"
_COL_USER = "利用者"
_COL_TID = "取引番号"


def parse_csv(path: Path, config: AppConfig) -> list[Transaction]:
    """PayPay CSV ファイルをパースして Transaction のリストを返す。

    エンコーディングを自動検出し、複合支払いを集約する。

    Args:
        path: 入力 CSV ファイルのパス。
        config: アプリケーション設定。

    Returns:
        パースされた Transaction のリスト。

    Raises:
        ValueError: エンコーディングの自動検出に失敗した場合。
    """
    encoding = _detect_encoding(path, config.parser.encoding_priority)
    rows = _read_rows(path, encoding)
    merged = _merge_compound(rows)
    return [_to_transaction(r, config.parser.date_formats) for r in merged]


def _can_read_with_encoding(path: Path, enc: str) -> bool:
    """指定エンコーディングでファイルを読み込めるか確認する。

    Args:
        path: CSV ファイルのパス。
        enc: 試すエンコーディング名。

    Returns:
        読み込みに成功した場合 True、失敗した場合 False。
    """
    try:
        with path.open(encoding=enc) as f:
            f.read()
    except (UnicodeDecodeError, LookupError):
        return False
    else:
        return True


def _detect_encoding(path: Path, priority: list[str]) -> str:
    """CSV ファイルのエンコーディングを自動検出する。

    priority の順で読み込みを試みる。

    Args:
        path: CSV ファイルのパス。
        priority: 試すエンコーディング名のリスト。小文字。

    Returns:
        検出されたエンコーディング名。

    Raises:
        ValueError: priority リストのいずれのエンコーディングでも読み込めなかった場合。
    """
    for enc in priority:
        if _can_read_with_encoding(path, enc):
            return enc
    raise ValueError(_ERR_UNSUPPORTED_ENCODING.format(path))


def _read_rows(path: Path, encoding: str) -> list[dict]:
    """CSV ファイルを指定エンコーディングで読み込み、行辞書のリストを返す。

    BOM 付き UTF-8 にも対応する。

    Args:
        path: CSV ファイルのパス。
        encoding: 使用するエンコーディング。

    Returns:
        各行を辞書で表したリスト。
    """
    with path.open(encoding=encoding, newline="") as f:
        content = f.read()
    # BOM 付き UTF-8 対応
    content = content.lstrip(_UTF8_BOM)
    reader = csv.DictReader(content.splitlines())
    return [dict(row) for row in reader]


def _parse_amount(s: str) -> int:
    """CSV セルの金額文字列を整数に変換する。

    カンマ区切りや CSV スタイルの二重引用符、"-" や空文字を処理する。

    Args:
        s: 金額文字列。例: ``"1,280"``、``"-"``、``""``

    Returns:
        金額の整数値。変換できない場合は 0。
    """
    stripped = s.strip().strip('"')
    if stripped in ("-", "", "ー"):
        return 0
    return int(re.sub(r"[,，]", "", stripped))


def _merge_compound(rows: list[dict]) -> list[dict]:
    """同一取引番号を持つ複数行を1行に集約する。

    同じ取引番号の行は金額を合算し、最初の行の他フィールドを保持する。
    取引番号が空の行はそのまま通過させる。

    Args:
        rows: CSV の行辞書のリスト。

    Returns:
        集約後の行辞書のリスト。
    """
    seen: dict[str, dict] = {}
    order: list[str] = []

    for row in rows:
        tid = (row.get(_COL_TID) or "").strip()
        if not tid:
            # 取引番号なし → 独立行として追加
            key = f"__no_id_{len(seen)}"
            seen[key] = row
            order.append(key)
            continue

        if tid in seen:
            # 複合支払: 出金・入金それぞれ合算
            existing = seen[tid]
            existing[_COL_OUT_AMOUNT] = str(
                _parse_amount(existing[_COL_OUT_AMOUNT])
                + _parse_amount(row[_COL_OUT_AMOUNT]),
            )
            existing[_COL_IN_AMOUNT] = str(
                _parse_amount(existing[_COL_IN_AMOUNT])
                + _parse_amount(row[_COL_IN_AMOUNT]),
            )
        else:
            seen[tid] = row
            order.append(tid)

    return [seen[k] for k in order]


def _to_transaction(
    row: dict, date_formats: list[str],
) -> Transaction:
    """行辞書を Transaction オブジェクトに変換する。

    海外取引の場合はメモに国・通貨・変換レートを追記する。

    Args:
        row: CSV の行辞書。
        date_formats: 日付パースに使うフォーマット候補のリスト。

    Returns:
        変換された Transaction オブジェクト。
    """
    date = _parse_date(row[_COL_TRADE_DATE].strip(), date_formats)
    out_amount = _parse_amount(row[_COL_OUT_AMOUNT])
    in_amount = _parse_amount(row[_COL_IN_AMOUNT])

    if out_amount > 0:
        amount = out_amount
        direction = "out"
    else:
        amount = in_amount
        direction = "in"

    memo = row[_COL_CONTENT].strip()
    foreign = row.get(_COL_FOREIGN, "-").strip()
    currency = row.get(_COL_CURRENCY, "-").strip()
    if foreign not in ("-", ""):
        memo = f"{memo}（海外: {foreign} {currency}）"

    merchant = row[_COL_MERCHANT].strip()
    tid = (row.get(_COL_TID) or "").strip() or None

    return Transaction(
        date=date,
        amount=amount,
        direction=direction,
        memo=memo,
        merchant=merchant,
        transaction_id=tid,
    )


def _try_strptime(s: str, fmt: str) -> datetime | None:
    """1つのフォーマットで日付文字列のパースを試みる。

    Args:
        s: 日付文字列。
        fmt: strptime フォーマット文字列。

    Returns:
        パース成功なら datetime、失敗なら None。
    """
    try:
        return datetime.strptime(s, fmt) # noqa: DTZ007
    except ValueError:
        return None


def _parse_date(s: str, formats: list[str]) -> datetime:
    """日付文字列を datetime に変換する。

    formats のフォーマット候補を先頭から順に試みる。

    Args:
        s: 日付文字列。例: ``"2025/02/11 19:24:02"``
        formats: パースに使う strptime フォーマット候補のリスト。

    Returns:
        変換された datetime オブジェクト。

    Raises:
        ValueError: どのフォーマットにもマッチしなかった場合。
    """
    for fmt in formats:
        result = _try_strptime(s, fmt)
        if result is not None:
            return result
    raise ValueError(_ERR_DATE_PARSE_FAILED.format(s))
