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

from src.models import AppConfig, ParseFailure, Transaction

# UTF8 BOM
_UTF8_BOM = "\ufeff"

# エラーメッセージ定数
_ERR_UNSUPPORTED_ENCODING = "対応するエンコーディングで読み込めません: {}"
_ERR_DATE_PARSE_FAILED = "日付のパースに失敗しました: {!r}"
_ERR_REQUIRED_COLUMN_MISSING = "必須列が欠損しています: {!r}"
_ERR_REQUIRED_VALUE_MISSING = "必須列の値が空です: {!r}"

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

CsvRow = tuple[int, dict[str, str | None]]


def parse_csv(
    path: Path, config: AppConfig,
) -> tuple[list[Transaction], list[ParseFailure]]:
    """PayPay CSV ファイルをパースして結果と解析失敗を返す。

    エンコーディングを自動検出し、複合支払いを集約する。
    行単位の変換失敗は ParseFailure として収集し、正常行の処理を継続する。

    Args:
        path: 入力 CSV ファイルのパス。
        config: アプリケーション設定。

    Returns:
        （パースされた Transaction のリスト、解析失敗のリスト）のタプル。

    Raises:
        ValueError: エンコーディングの自動検出に失敗した場合など、
            ファイル全体を処理できない場合。
    """
    encoding = _detect_encoding(path, config.parser.encoding_priority)
    rows = _read_rows(path, encoding)
    merged = _merge_compound(rows)
    return _to_transactions(merged, config.parser.date_formats)


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


def _read_rows(path: Path, encoding: str) -> list[CsvRow]:
    """CSV ファイルを指定エンコーディングで読み込み、行辞書のリストを返す。

    BOM 付き UTF-8 にも対応する。

    Args:
        path: CSV ファイルのパス。
        encoding: 使用するエンコーディング。

    Returns:
        各行の物理行番号と辞書を組み合わせたリスト。
    """
    with path.open(encoding=encoding, newline="") as f:
        content = f.read()
    # BOM 付き UTF-8 対応
    content = content.lstrip(_UTF8_BOM)
    reader = csv.DictReader(content.splitlines())
    return [(i, dict(row)) for i, row in enumerate(reader, start=2)]


def _parse_amount(s: str | None) -> int:
    """CSV セルの金額文字列を整数に変換する。

    カンマ区切りや CSV スタイルの二重引用符、"-" や空文字を処理する。

    Args:
        s: 金額文字列。例: ``"1,280"``、``"-"``、``""``

    Returns:
        金額の整数値。変換できない場合は 0。
    """
    if s is None:
        raise ValueError(_ERR_REQUIRED_VALUE_MISSING.format("金額"))
    stripped = s.strip().strip('"')
    if stripped in ("-", "", "ー"):
        return 0
    return int(re.sub(r"[,，]", "", stripped))


def _merge_compound(rows: list[CsvRow]) -> list[CsvRow]:
    """同一取引番号を持つ複数行を1行に集約する。

    同じ取引番号の行は金額を合算し、最初の行の他フィールドを保持する。
    取引番号が空の行はそのまま通過させる。

    Args:
        rows: CSV の行辞書のリスト。

    Returns:
        集約後の行番号付き行辞書のリスト。
    """
    seen: dict[str, CsvRow] = {}
    order: list[str] = []

    for row_index, row in rows:
        tid = (row.get(_COL_TID) or "").strip()
        if not tid:
            # 取引番号なし → 独立行として追加
            key = f"__no_id_{len(seen)}"
            seen[key] = (row_index, row)
            order.append(key)
            continue

        if tid in seen:
            # 複合支払: 出金・入金それぞれ合算
            _, existing = seen[tid]
            existing[_COL_OUT_AMOUNT] = str(
                _parse_amount(existing[_COL_OUT_AMOUNT])
                + _parse_amount(row[_COL_OUT_AMOUNT]),
            )
            existing[_COL_IN_AMOUNT] = str(
                _parse_amount(existing[_COL_IN_AMOUNT])
                + _parse_amount(row[_COL_IN_AMOUNT]),
            )
        else:
            seen[tid] = (row_index, row)
            order.append(tid)

    return [seen[k] for k in order]


def _to_transactions(
    rows: list[CsvRow], date_formats: list[str],
) -> tuple[list[Transaction], list[ParseFailure]]:
    """行番号付きの行辞書リストを Transaction と ParseFailure に分離する。"""
    transactions: list[Transaction] = []
    failures: list[ParseFailure] = []

    for row_index, row in rows:
        transaction, failure = _parse_row(row_index, row, date_formats)
        if transaction is not None:
            transactions.append(transaction)
        if failure is not None:
            failures.append(failure)

    return transactions, failures


def _parse_row(
    row_index: int, row: dict[str, str | None], date_formats: list[str],
) -> tuple[Transaction | None, ParseFailure | None]:
    """単一行を Transaction または ParseFailure に変換する。"""
    try:
        return _to_transaction(row, date_formats), None
    except Exception as exc:
        return None, _build_parse_failure(row_index, row, exc)


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
    date = _parse_date(_get_required_value(row, _COL_TRADE_DATE), date_formats)
    out_amount = _parse_amount(_get_required_value(row, _COL_OUT_AMOUNT))
    in_amount = _parse_amount(_get_required_value(row, _COL_IN_AMOUNT))

    if out_amount > 0:
        amount = out_amount
        direction = "out"
    else:
        amount = in_amount
        direction = "in"

    memo = _get_required_value(row, _COL_CONTENT)
    foreign = (row.get(_COL_FOREIGN) or "-").strip()
    currency = (row.get(_COL_CURRENCY) or "-").strip()
    if foreign not in ("-", ""):
        memo = f"{memo}（海外: {foreign} {currency}）"

    merchant = _get_required_value(row, _COL_MERCHANT)
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


def _get_required_value(row: dict[str, str | None], key: str) -> str:
    """必須列の値を取得する。"""
    if key not in row:
        raise KeyError(_ERR_REQUIRED_COLUMN_MISSING.format(key))

    value = row[key]
    if value is None:
        raise ValueError(_ERR_REQUIRED_VALUE_MISSING.format(key))

    return value.strip()


def _build_parse_failure(
    row_index: int, row: dict[str, str | None], exc: Exception,
) -> ParseFailure:
    """例外内容から ParseFailure を生成する。"""
    normalized_row = {
        key: "" if value is None else str(value)
        for key, value in row.items()
    }
    return ParseFailure(
        row_index=row_index,
        transaction_id=(row.get(_COL_TID) or "").strip() or None,
        merchant=(row.get(_COL_MERCHANT) or "").strip() or None,
        error_type=_classify_parse_error(exc),
        error_message=str(exc),
        raw_row=normalized_row,
    )


def _classify_parse_error(exc: Exception) -> str:
    """例外から解析エラー種別を決定する。"""
    if isinstance(exc, KeyError):
        return "missing_column"
    if isinstance(exc, ValueError):
        if str(exc).startswith("日付のパースに失敗しました"):
            return "invalid_date"
        return "invalid_value"
    return "conversion_error"
