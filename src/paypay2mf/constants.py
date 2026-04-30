"""プロジェクト全体で共有する定数。"""

from __future__ import annotations


class AppConstants:
    """複数モジュールで共有するアプリケーション定数。"""

    # 取引データの方向を表す定数。
    DIRECTION_IN = "in"
    DIRECTION_OUT = "out"

    # カテゴリや空文字などの基本値。
    DEFAULT_CATEGORY = "未分類"
    EMPTY_STRING = ""

    # 除外対象の取引番号プレフィックス。
    EXCLUDE_PREFIX_PAYPAY_CARD = "PPCD_A_"

    # カテゴリマッピングで使うマッチモード。
    MATCH_MODE_CONTAINS = "contains"
    MATCH_MODE_STARTS_WITH = "starts_with"
    MATCH_MODE_REGEX = "regex"
    DEFAULT_MATCH_MODE = MATCH_MODE_CONTAINS
    VALID_MATCH_MODES = frozenset(
        {
            MATCH_MODE_CONTAINS,
            MATCH_MODE_STARTS_WITH,
            MATCH_MODE_REGEX,
        },
    )

    # 重複検知バックエンドの識別子。
    BACKEND_LOCAL = "local"
    BACKEND_GCLOUD = "gcloud"
    DEFAULT_BACKEND = BACKEND_LOCAL
    DEFAULT_FIRESTORE_DATABASE_ID = "(default)"

    # 文字コード判定と既定値に使う定数。
    ENCODING_UTF8 = "utf-8"
    ENCODING_UTF8_ALT = "utf8"
    ENCODING_UTF8_SIG = "utf-8-sig"
    ENCODING_SHIFT_JIS = "shift_jis"
    DEFAULT_TEXT_ENCODING = ENCODING_UTF8
    DEFAULT_ENCODING_PRIORITY = (
        ENCODING_UTF8,
        ENCODING_SHIFT_JIS,
    )

    # ファイル拡張子の共通定義。
    CSV_EXTENSION = ".csv"
    LOG_FILE_EXTENSION = ".log"
    PNG_EXTENSION = ".png"

    # 日付入力やファイル名生成に使う書式。
    CSV_DATE_FORMAT = "%Y/%m/%d %H:%M:%S"
    FORM_DATE_FORMAT = "%Y/%m/%d"
    TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
    DUPLICATE_KEY_DATE_FORMAT = "%Y%m%d%H%M%S"
    DEFAULT_DATE_FORMATS = (CSV_DATE_FORMAT,)

    # ログや重複管理ファイルの既定名。
    DEFAULT_LOGS_DIR = "logs"
    PROCESSED_FILENAME = "processed.json"
    DEFAULT_EXCLUDE_PREFIXES = (EXCLUDE_PREFIX_PAYPAY_CARD,)

    # Chrome 起動時の実行設定。
    CHROME_EXECUTABLE = "chrome.exe"
    CHROME_CHANNEL = "chrome"
    CHROME_PROFILE_DIRECTORY_ARG = "--profile-directory={}"

    # UI 操作に使う固定値。
    LOCATOR_STATE_VISIBLE = "visible"
    LOCATOR_STATE_HIDDEN = "hidden"
    KEY_ESCAPE = "Escape"

    # 文字列処理に使う共通記号。
    HYPHEN = "-"
    WAVE_DASH = "ー"
    UNDERSCORE = "_"
    NEWLINE = "\n"
