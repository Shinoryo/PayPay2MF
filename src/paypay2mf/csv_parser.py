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

from paypay2mf.constants import AppConstants
from paypay2mf.duplicate_detector import build_row_fingerprint
from paypay2mf.models import AppConfig, ParseFailure, Transaction

# エンコーディング判定に使う定数。
_ENCODING_CHECK_CHUNK_SIZE = 8192
_UTF8_ENCODING_NAMES = {
    AppConstants.ENCODING_UTF8,
    AppConstants.ENCODING_UTF8_ALT,
}

# 金額文字列の正規化に使う定数。
_AMOUNT_FIELD_NAME = "金額"
_AMOUNT_STRIP_CHAR = '"'
_AMOUNT_SEPARATOR_PATTERN = r"[,，]"
_ZERO_AMOUNT_MARKERS = (
    AppConstants.HYPHEN,
    AppConstants.EMPTY_STRING,
    AppConstants.WAVE_DASH,
)

# エラー分類に使う定数。
_FOREIGN_MEMO_TEMPLATE = "{}（海外: {} {}）"
_PARSE_ERROR_MISSING_COLUMN = "missing_column"
_PARSE_ERROR_INVALID_DATE = "invalid_date"
_PARSE_ERROR_INVALID_VALUE = "invalid_value"
_PARSE_ERROR_CONVERSION = "conversion_error"
_DATE_PARSE_ERROR_PREFIX = "日付のパースに失敗しました"

# エラーメッセージ定数
_ERR_UNSUPPORTED_ENCODING = "対応するエンコーディングで読み込めません: {}"
_ERR_DATE_PARSE_FAILED = "日付のパースに失敗しました: {!r}"
_ERR_REQUIRED_COLUMN_MISSING = "必須列が欠損しています: {!r}"
_ERR_REQUIRED_VALUE_MISSING = "必須列の値が空です: {!r}"
_ERR_ZERO_AMOUNT_TRANSACTION = "出金金額と入金金額の両方が0です"
_ERR_AMBIGUOUS_AMOUNT_TRANSACTION = "出金金額と入金金額の両方に正の値があります"
_ERR_INVALID_AMOUNT_TRANSACTION = (
    "出金金額と入金金額のどちらか一方のみ正の値である必要があります"
)

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
    path: Path,
    config: AppConfig,
) -> tuple[list[Transaction], list[ParseFailure]]:
    """PayPay CSV ファイルをパースして結果と解析失敗を返す。

    エンコーディングを自動検出し、CSV 各行をそのまま変換する。
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
    return _to_transactions(rows, config.parser.date_formats)


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
            for chunk in iter(
                lambda: f.read(_ENCODING_CHECK_CHUNK_SIZE),
                AppConstants.EMPTY_STRING,
            ):
                if not chunk:
                    break
    except (UnicodeDecodeError, LookupError):
        return False
    else:
        return True


def _resolve_csv_encoding(encoding: str) -> str:
    normalized = encoding.replace(AppConstants.UNDERSCORE, AppConstants.HYPHEN).lower()
    if normalized in _UTF8_ENCODING_NAMES:
        return AppConstants.ENCODING_UTF8_SIG
    return encoding


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
    with path.open(
        encoding=_resolve_csv_encoding(encoding),
        newline=AppConstants.EMPTY_STRING,
    ) as f:
        reader = csv.DictReader(f)
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
        raise ValueError(_ERR_REQUIRED_VALUE_MISSING.format(_AMOUNT_FIELD_NAME))
    stripped = s.strip().strip(_AMOUNT_STRIP_CHAR)
    if stripped in _ZERO_AMOUNT_MARKERS:
        return 0
    return int(re.sub(_AMOUNT_SEPARATOR_PATTERN, AppConstants.EMPTY_STRING, stripped))


def _to_transactions(
    rows: list[CsvRow],
    date_formats: list[str],
) -> tuple[list[Transaction], list[ParseFailure]]:
    """行番号付きの行辞書リストを Transaction と ParseFailure に分離する。"""
    transactions: list[Transaction] = []
    failures: list[ParseFailure] = []

    for data_idx, (row_index, row) in enumerate(rows, start=1):
        transaction, failure = _parse_row(row_index, row, date_formats)
        if transaction is not None:
            transaction.row_index = data_idx
            transactions.append(transaction)
        if failure is not None:
            failures.append(failure)

    return transactions, failures


def _parse_row(
    row_index: int,
    row: dict[str, str | None],
    date_formats: list[str],
) -> tuple[Transaction | None, ParseFailure | None]:
    """単一行を Transaction または ParseFailure に変換する。"""
    try:
        return _to_transaction(row, date_formats), None
    except Exception as exc:
        return None, _build_parse_failure(row_index, row, exc)


def _to_transaction(
    row: dict,
    date_formats: list[str],
) -> Transaction:
    """行辞書を Transaction オブジェクトに変換する。

    海外取引の場合はメモに国・通貨・変換レートを追記する。

    Args:
        row: CSV の行辞書。
        date_formats: 日付パースに使うフォーマット候補のリスト。

    Returns:
        変換された Transaction オブジェクト。
    """
    trade_date_text = _get_required_value(row, _COL_TRADE_DATE)
    out_amount_text = _get_required_value(row, _COL_OUT_AMOUNT)
    in_amount_text = _get_required_value(row, _COL_IN_AMOUNT)
    content = _get_required_value(row, _COL_CONTENT)

    date = _parse_date(trade_date_text, date_formats)
    out_amount = _parse_amount(out_amount_text)
    in_amount = _parse_amount(in_amount_text)
    amount, direction = _resolve_transaction_amount(out_amount, in_amount)

    merchant = _get_required_value(row, _COL_MERCHANT)
    method = _normalize_optional_text(row.get(_COL_METHOD))
    payment_type = _normalize_optional_text(row.get(_COL_PAYMENT_TYPE))
    user = _normalize_optional_text(row.get(_COL_USER))
    foreign = (row.get(_COL_FOREIGN) or AppConstants.HYPHEN).strip()
    currency = (row.get(_COL_CURRENCY) or AppConstants.HYPHEN).strip()
    memo = merchant
    if foreign not in (AppConstants.HYPHEN, AppConstants.EMPTY_STRING):
        memo = _FOREIGN_MEMO_TEMPLATE.format(memo, foreign, currency)
    tid = (row.get(_COL_TID) or AppConstants.EMPTY_STRING).strip() or None
    row_fingerprint = build_row_fingerprint(
        date_text=trade_date_text,
        content=content,
        merchant=merchant,
        out_amount=out_amount,
        in_amount=in_amount,
        method=method,
        payment_type=payment_type,
        user=user,
    )

    return Transaction(
        date=date,
        amount=amount,
        direction=direction,
        memo=memo,
        merchant=merchant,
        transaction_id=tid,
        date_text=trade_date_text,
        content=content,
        method=method,
        payment_type=payment_type,
        user=user,
        row_fingerprint=row_fingerprint,
    )


def _normalize_optional_text(value: str | None) -> str:
    """指紋生成で使う任意列値を正規化する。"""
    if value is None:
        return AppConstants.EMPTY_STRING
    return value.strip()


def _resolve_transaction_amount(out_amount: int, in_amount: int) -> tuple[int, str]:
    """出金額と入金額から登録対象の金額と方向を確定する。"""
    if out_amount == 0 and in_amount == 0:
        raise ValueError(_ERR_ZERO_AMOUNT_TRANSACTION)
    if out_amount > 0 and in_amount > 0:
        raise ValueError(_ERR_AMBIGUOUS_AMOUNT_TRANSACTION)
    if out_amount > 0:
        return out_amount, AppConstants.DIRECTION_OUT
    if in_amount > 0:
        return in_amount, AppConstants.DIRECTION_IN
    raise ValueError(_ERR_INVALID_AMOUNT_TRANSACTION)


def _try_strptime(s: str, fmt: str) -> datetime | None:
    """1つのフォーマットで日付文字列のパースを試みる。

    Args:
        s: 日付文字列。
        fmt: strptime フォーマット文字列。

    Returns:
        パース成功なら datetime、失敗なら None。
    """
    try:
        return datetime.strptime(s, fmt)  # noqa: DTZ007
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

    stripped = value.strip()
    if not stripped:
        raise ValueError(_ERR_REQUIRED_VALUE_MISSING.format(key))

    return stripped


def _build_parse_failure(
    row_index: int,
    row: dict[str, str | None],
    exc: Exception,
) -> ParseFailure:
    """例外内容から ParseFailure を生成する。"""
    normalized_row = {
        key: AppConstants.EMPTY_STRING if value is None else str(value)
        for key, value in row.items()
    }
    return ParseFailure(
        row_index=row_index,
        transaction_id=(row.get(_COL_TID) or AppConstants.EMPTY_STRING).strip() or None,
        merchant=(row.get(_COL_MERCHANT) or AppConstants.EMPTY_STRING).strip() or None,
        error_type=_classify_parse_error(exc),
        error_message=str(exc),
        raw_row=normalized_row,
    )


def _classify_parse_error(exc: Exception) -> str:
    """例外から解析エラー種別を決定する。"""
    if isinstance(exc, KeyError):
        return _PARSE_ERROR_MISSING_COLUMN
    if isinstance(exc, ValueError):
        if str(exc).startswith(_DATE_PARSE_ERROR_PREFIX):
            return _PARSE_ERROR_INVALID_DATE
        return _PARSE_ERROR_INVALID_VALUE
    return _PARSE_ERROR_CONVERSION
