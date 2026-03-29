"""PayPay→MoneyForward 自動登録ツールのデータモデル定義。

CSV パース結果・設定ファイル内容を格納する dataclass 群を提供する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from paypay2mf.constants import AppConstants

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path


@dataclass
class MappingRule:
    """カテゴリマッピングルールの定義。

    Attributes:
        keyword: マッチングに使うキーワード。
        category: MF に登録するカテゴリ名。
        match_mode: マッチモード。"contains" / "starts_with" / "regex" のいずれか。
        priority: 評価優先度。数値が大きいほど先に評価される。
    """

    keyword: str
    category: str
    match_mode: str = AppConstants.DEFAULT_MATCH_MODE
    priority: int = 0


@dataclass
class Transaction:
    """PayPay 利用明細の1件分のデータ。

    Attributes:
        date: 取引日時。
        amount: 取引金額（円・整数）。
        direction: 入出金方向。"out"（出金）または "in"（入金）。
        memo: MF メモ欄に転記する文字列 (取引内容 + 海外情報)。
        merchant: 取引先名 (マッピングルールのマッチング対象)。
        transaction_id: 取引番号。複数行に分割された場合でも同一 ID を共有する。
            取引番号が存在しない行は None。
        category: マッピング後のカテゴリ名。デフォルト値は "未分類"。
    """

    date: datetime
    amount: int
    direction: str  # AppConstants.DIRECTION_IN or AppConstants.DIRECTION_OUT
    memo: str
    merchant: str
    transaction_id: str | None
    category: str = AppConstants.DEFAULT_CATEGORY


@dataclass
class ParseFailure:
    """CSV 解析失敗の記録。"""

    row_index: int
    transaction_id: str | None
    merchant: str | None
    error_type: str
    error_message: str
    raw_row: dict[str, str]


@dataclass
class DuplicateDetectionConfig:
    """重複検知の設定。

    Attributes:
        backend: 重複履歴の保存先。
            "local"（JSON ファイル）または "gcloud"（Firestore）。
        tolerance_seconds: 取引番号欠損時の日時比較許容幅（秒）。
    """

    backend: str = AppConstants.DEFAULT_BACKEND
    tolerance_seconds: int = 60


@dataclass
class ParserConfig:
    """CSV パーサーの設定。

    Attributes:
        encoding_priority: CSV 読み込み時に試す文字コードの優先順リスト。
        date_formats: 取引日のパースに使うフォーマット候補（先頭から順に試す）。
    """

    encoding_priority: list[str] = field(
        default_factory=lambda: [
            AppConstants.ENCODING_UTF8,
            AppConstants.ENCODING_SHIFT_JIS,
        ],
    )
    date_formats: list[str] = field(
        default_factory=lambda: [AppConstants.CSV_DATE_FORMAT],
    )


@dataclass
class LogSettings:
    """ログ出力の設定。

    Attributes:
        logs_dir: ログ・スクリーンショット・エラー CSV の保存先。
            None の場合は ``<tool_folder>/logs`` を使用する。
        max_log_count: 保持するログファイル数の上限。None は無制限。
        max_total_log_size_mb: ログの合計サイズ上限（MB）。None は無制限。
    """

    logs_dir: Path | None = None
    max_log_count: int | None = None
    max_total_log_size_mb: int | None = None


@dataclass
class AdvancedConfig:
    """高度な動作設定。

    Attributes:
        screenshot_on_error: True の場合のみ、
            エラー発生時にスクリーンショットを保存する。
        mf_categories_path: Money Forward カテゴリマップ YAML の上書きパス。
            None の場合は同梱の既定マップを使用する。
    """

    screenshot_on_error: bool = False
    mf_categories_path: Path | None = None


@dataclass
class AppConfig:
    """アプリケーション全設定をまとめた最上位の dataclass。

    Attributes:
        chrome_user_data_dir: Chrome のユーザーデータディレクトリのパス。
        chrome_profile: Chrome のプロファイル名（例: "Default"）。
        dry_run: True の場合、MF への実際の登録や重複履歴の更新は行わず、
            診断ログのみを出力する。
        input_csv: 入力 CSV ファイルのパス。
        mf_account: MF の登録先口座名。
        mapping_rules: カテゴリマッピングルールのリスト。
        exclude_prefixes: 除外対象の取引番号プレフィックスのリスト。
        gcloud_credentials_path: Google Cloud 認証情報ファイルのパス。
        duplicate_detection: 重複検知の設定。
        parser: CSV パーサーの設定。
        log_settings: ログ出力の設定。
        advanced: 高度な動作設定。
    """

    chrome_user_data_dir: str
    chrome_profile: str
    dry_run: bool
    input_csv: Path
    mf_account: str
    mapping_rules: list[MappingRule] = field(default_factory=list)
    exclude_prefixes: list[str] = field(
        default_factory=lambda: [AppConstants.EXCLUDE_PREFIX_PAYPAY_CARD],
    )
    gcloud_credentials_path: Path | None = None
    duplicate_detection: DuplicateDetectionConfig = field(
        default_factory=DuplicateDetectionConfig,
    )
    parser: ParserConfig = field(default_factory=ParserConfig)
    log_settings: LogSettings = field(default_factory=LogSettings)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)
