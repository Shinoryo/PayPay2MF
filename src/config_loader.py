"""設定ファイルの読み込みと検証。

YAML 形式の設定ファイルを読み込み、必須項目・型・パスを検証して
AppConfig インスタンスに変換する。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.constants import AppConstants
from src.models import (
    AdvancedConfig,
    AppConfig,
    DuplicateDetectionConfig,
    LogSettings,
    MappingRule,
    ParserConfig,
)

# 設定ファイル キー名 トップレベル
_KEY_CHROME_USER_DATA_DIR = "chrome_user_data_dir"
_KEY_CHROME_PROFILE = "chrome_profile"
_KEY_DRY_RUN = "dry_run"
_KEY_INPUT_CSV = "input_csv"
_KEY_MF_ACCOUNT = "mf_account"
_KEY_MAPPING_RULES = "mapping_rules"
_KEY_EXCLUDE_PREFIXES = "exclude_prefixes"
_KEY_GCLOUD_CREDENTIALS_PATH = "gcloud_credentials_path"
_KEY_DUPLICATE_DETECTION = "duplicate_detection"
_KEY_PARSER = "parser"
_KEY_LOG_SETTINGS = "log_settings"
_KEY_ADVANCED = "advanced"

# 設定ファイル キー名 duplicate_detection サブキー
_KEY_DD_BACKEND = "backend"
_KEY_DD_TOLERANCE_SECONDS = "tolerance_seconds"

# 設定ファイル キー名 parser サブキー
_KEY_PARSER_ENCODING_PRIORITY = "encoding_priority"
_KEY_PARSER_DATE_FORMATS = "date_formats"

# 設定ファイル キー名 log_settings サブキー
_KEY_LOG_LOGS_DIR = "logs_dir"
_KEY_LOG_MAX_LOG_COUNT = "max_log_count"
_KEY_LOG_MAX_TOTAL_LOG_SIZE_MB = "max_total_log_size_mb"

# 設定ファイル キー名 advanced サブキー
_KEY_ADV_SCREENSHOT_ON_ERROR = "screenshot_on_error"
_KEY_ADV_MF_CATEGORIES_PATH = "mf_categories_path"

# 設定ファイル キー名 mapping_rules アイテムキー
_KEY_RULE_KEYWORD = "keyword"
_KEY_RULE_CATEGORY = "category"
_KEY_RULE_MATCH_MODE = "match_mode"
_KEY_RULE_PRIORITY = "priority"

# デフォルト値
_DEFAULT_PRIORITY = 0
_DEFAULT_TOLERANCE_SECONDS = 60
_DEFAULT_SCREENSHOT_ON_ERROR = False

# エラーメッセージ
_MSG_CONFIG_NOT_FOUND = "config.yml が見つかりません: {path}"
_MSG_DRY_RUN_TYPE = "dry_run には true または false を指定してください。"

_MSG_REQUIRED_CHROME_USER_DATA_DIR = (
    "chrome_user_data_dir が設定されていません。config.yml に記載してください。"
)
_MSG_REQUIRED_CHROME_PROFILE = (
    "chrome_profile が設定されていません。config.yml に記載してください。"
)
_MSG_REQUIRED_DRY_RUN = (
    "dry_run が設定されていません。true または false を config.yml に記載してください。"
)
_MSG_REQUIRED_INPUT_CSV = (
    "input_csv が設定されていません。config.yml に記載してください。"
)
_MSG_REQUIRED_MF_ACCOUNT = (
    "mf_account が設定されていません。config.yml に記載してください。"
)

_MSG_CHROME_USER_DATA_DIR_NOT_EXIST = (
    "chrome_user_data_dir のパスが存在しません: {path}"
)
_MSG_CHROME_PROFILE_NOT_EXIST = "chrome_profile のディレクトリが存在しません: {path}"
_MSG_INPUT_CSV_NOT_EXIST = "input_csv のファイルが存在しません: {path}"
_MSG_INPUT_CSV_BAD_EXT = "input_csv の拡張子が .csv ではありません: {path}"

_MSG_MAPPING_KEYWORD_EMPTY = "mapping_rules[{i}]: keyword が空です。"
_MSG_MAPPING_CATEGORY_EMPTY = "mapping_rules[{i}]: category が空です。"
_MSG_MAPPING_MATCH_MODE_INVALID = (
    "mapping_rules[{i}]: match_mode が無効です: {mode!r} （有効値: {valids}）"
)

_MSG_GCLOUD_CREDS_REQUIRED = (
    'duplicate_detection.backend: "gcloud" の場合は '
    "gcloud_credentials_path の指定が必要です。"
)
_MSG_GCLOUD_CREDS_NOT_EXIST = "gcloud_credentials_path のファイルが存在しません: {path}"
_MSG_MF_CATEGORIES_NOT_EXIST = (
    "advanced.mf_categories_path のファイルが存在しません: {path}"
)

_REQUIRED_KEYS: dict[str, str] = {
    _KEY_CHROME_USER_DATA_DIR: _MSG_REQUIRED_CHROME_USER_DATA_DIR,
    _KEY_CHROME_PROFILE: _MSG_REQUIRED_CHROME_PROFILE,
    _KEY_DRY_RUN: _MSG_REQUIRED_DRY_RUN,
    _KEY_INPUT_CSV: _MSG_REQUIRED_INPUT_CSV,
    _KEY_MF_ACCOUNT: _MSG_REQUIRED_MF_ACCOUNT,
}

_REQUIRED_STRING_KEYS = {
    _KEY_CHROME_USER_DATA_DIR,
    _KEY_CHROME_PROFILE,
    _KEY_INPUT_CSV,
    _KEY_MF_ACCOUNT,
}


def load_config(path: Path) -> AppConfig:
    """YAML 設定ファイルを読み込み、検証済みの AppConfig を返す。

    Args:
        path: 設定ファイルのパス。

    Returns:
        検証済みの AppConfig インスタンス。

    Raises:
        FileNotFoundError: 設定ファイルが存在しない場合。
        ValueError: 必須項目の欠落・型不正・パス検証エラーの場合。
    """
    if not path.exists():
        raise FileNotFoundError(_MSG_CONFIG_NOT_FOUND.format(path=path))

    with path.open(encoding=AppConstants.DEFAULT_TEXT_ENCODING) as f:
        raw: dict = yaml.safe_load(f) or {}

    _validate_required(raw)
    _validate_paths(
        raw,
        skip_chrome_validation=raw[_KEY_DRY_RUN],
        config_dir=path.parent,
    )
    _validate_mapping_rules(raw.get(_KEY_MAPPING_RULES) or [])
    _validate_gcloud(raw, config_dir=path.parent)
    return _build_config(raw, config_dir=path.parent)


def _validate_required(raw: dict) -> None:
    """必須キーの存在と型を検証する。

    Args:
        raw: YAML から読み込んだ辞書。

    Raises:
        ValueError: 必須キーが欠落している場合、または dry_run の値が bool でない場合。
    """
    errors: list[str] = []
    for key, msg in _REQUIRED_KEYS.items():
        value = raw.get(key)
        if value is None:
            errors.append(msg)
            continue
        if key in _REQUIRED_STRING_KEYS and not str(value).strip():
            errors.append(msg)
    dry_run_val = raw.get(_KEY_DRY_RUN)
    if dry_run_val is not None and not isinstance(dry_run_val, bool):
        errors.append(_MSG_DRY_RUN_TYPE)
    if errors:
        raise ValueError("\n".join(errors))


def _validate_paths(
    raw: dict,
    *,
    skip_chrome_validation: bool,
    config_dir: Path,
) -> None:
    """パス関連の項目を検証する。

    Args:
        raw: YAML から読み込んだ辞書。
        skip_chrome_validation: True の場合、Chrome 関連のパス検証を
            スキップする。
        config_dir: config.yml が置かれたディレクトリ。

    Raises:
        ValueError: chrome_user_data_dir が存在しない場合、または
            input_csv が存在しない場合。
    """
    errors: list[str] = []

    if not skip_chrome_validation:
        user_data_dir = Path(str(raw[_KEY_CHROME_USER_DATA_DIR]))

        if user_data_dir.exists():
            profile_dir = user_data_dir / str(raw[_KEY_CHROME_PROFILE])
            if not profile_dir.exists():
                errors.append(_MSG_CHROME_PROFILE_NOT_EXIST.format(path=profile_dir))
        else:
            errors.append(
                _MSG_CHROME_USER_DATA_DIR_NOT_EXIST.format(path=user_data_dir)
            )

    input_csv = _resolve_path(raw[_KEY_INPUT_CSV], config_dir)
    if not input_csv.exists():
        errors.append(_MSG_INPUT_CSV_NOT_EXIST.format(path=input_csv))
    elif input_csv.suffix.lower() != AppConstants.CSV_EXTENSION:
        errors.append(_MSG_INPUT_CSV_BAD_EXT.format(path=input_csv))

    advanced_raw = raw.get(_KEY_ADVANCED) or {}
    mf_categories_path = _resolve_optional_path(
        advanced_raw.get(_KEY_ADV_MF_CATEGORIES_PATH),
        config_dir,
    )
    if mf_categories_path is not None and not mf_categories_path.exists():
        errors.append(_MSG_MF_CATEGORIES_NOT_EXIST.format(path=mf_categories_path))

    if errors:
        raise ValueError("\n".join(errors))


def _resolve_path(raw_value: object, config_dir: Path) -> Path:
    """設定値のパスを config.yml 基準で解決する。"""
    candidate = Path(str(raw_value))
    if candidate.is_absolute():
        return candidate
    return config_dir / candidate


def _resolve_optional_path(raw_value: object, config_dir: Path) -> Path | None:
    """任意の設定パスを config.yml 基準で解決する。"""
    if raw_value in (None, ""):
        return None
    return _resolve_path(raw_value, config_dir)


def _validate_mapping_rules(rules: list) -> None:
    """mapping_rules の各要素を検証する。

    Args:
        rules: YAML から読み込んだ mapping_rules のリスト。

    Raises:
        ValueError: keyword が空文字の場合、または match_mode の値が不正な場合。
    """
    errors: list[str] = []
    for i, rule in enumerate(rules):
        if not rule.get(_KEY_RULE_KEYWORD):
            errors.append(_MSG_MAPPING_KEYWORD_EMPTY.format(i=i))
        if not rule.get(_KEY_RULE_CATEGORY):
            errors.append(_MSG_MAPPING_CATEGORY_EMPTY.format(i=i))
        mode = rule.get(_KEY_RULE_MATCH_MODE, AppConstants.DEFAULT_MATCH_MODE)
        if mode not in AppConstants.VALID_MATCH_MODES:
            valids = ", ".join(sorted(AppConstants.VALID_MATCH_MODES))
            errors.append(
                _MSG_MAPPING_MATCH_MODE_INVALID.format(i=i, mode=mode, valids=valids),
            )
    if errors:
        raise ValueError("\n".join(errors))


def _validate_gcloud(raw: dict, *, config_dir: Path) -> None:
    """gcloud バックエンド使用時の追加検証を行う。

    Args:
        raw: YAML から読み込んだ辞書。
        config_dir: config.yml が置かれたディレクトリ。

    Raises:
        ValueError: backend が "gcloud" なのに gcloud_credentials_path が
            未設定の場合、または認証情報ファイルが存在しない場合。
    """
    dd = raw.get(_KEY_DUPLICATE_DETECTION) or {}
    backend = dd.get(_KEY_DD_BACKEND, AppConstants.DEFAULT_BACKEND)
    creds = raw.get(_KEY_GCLOUD_CREDENTIALS_PATH)

    if backend == AppConstants.BACKEND_GCLOUD and not creds:
        raise ValueError(_MSG_GCLOUD_CREDS_REQUIRED)

    resolved_creds = _resolve_optional_path(creds, config_dir)
    if resolved_creds is not None and not resolved_creds.exists():
        raise ValueError(_MSG_GCLOUD_CREDS_NOT_EXIST.format(path=resolved_creds))


def _build_config(raw: dict, *, config_dir: Path) -> AppConfig:
    """検証済みの辞書から AppConfig を構築する。

    Args:
        raw: 検証済みの YAML 辞書。
        config_dir: config.yml が置かれたディレクトリ。

    Returns:
        AppConfig インスタンス。
    """
    mapping_rules = [
        MappingRule(
            keyword=r[_KEY_RULE_KEYWORD],
            category=r[_KEY_RULE_CATEGORY],
            match_mode=r.get(_KEY_RULE_MATCH_MODE, AppConstants.DEFAULT_MATCH_MODE),
            priority=r.get(_KEY_RULE_PRIORITY, _DEFAULT_PRIORITY),
        )
        for r in (raw.get(_KEY_MAPPING_RULES) or [])
    ]

    dd_raw = raw.get(_KEY_DUPLICATE_DETECTION) or {}
    dup = DuplicateDetectionConfig(
        backend=dd_raw.get(_KEY_DD_BACKEND, AppConstants.DEFAULT_BACKEND),
        tolerance_seconds=dd_raw.get(
            _KEY_DD_TOLERANCE_SECONDS,
            _DEFAULT_TOLERANCE_SECONDS,
        ),
    )

    parser_raw = raw.get(_KEY_PARSER) or {}
    parser = ParserConfig(
        encoding_priority=parser_raw.get(
            _KEY_PARSER_ENCODING_PRIORITY,
            list(AppConstants.DEFAULT_ENCODING_PRIORITY),
        ),
        date_formats=parser_raw.get(
            _KEY_PARSER_DATE_FORMATS,
            list(AppConstants.DEFAULT_DATE_FORMATS),
        ),
    )

    log_raw = raw.get(_KEY_LOG_SETTINGS) or {}
    logs_dir_raw = log_raw.get(_KEY_LOG_LOGS_DIR)
    log_settings = LogSettings(
        logs_dir=_resolve_optional_path(logs_dir_raw, config_dir),
        max_log_count=log_raw.get(_KEY_LOG_MAX_LOG_COUNT),
        max_total_log_size_mb=log_raw.get(_KEY_LOG_MAX_TOTAL_LOG_SIZE_MB),
    )

    adv_raw = raw.get(_KEY_ADVANCED) or {}
    advanced = AdvancedConfig(
        screenshot_on_error=adv_raw.get(
            _KEY_ADV_SCREENSHOT_ON_ERROR,
            _DEFAULT_SCREENSHOT_ON_ERROR,
        ),
        mf_categories_path=_resolve_optional_path(
            adv_raw.get(_KEY_ADV_MF_CATEGORIES_PATH),
            config_dir,
        ),
    )

    creds = _resolve_optional_path(raw.get(_KEY_GCLOUD_CREDENTIALS_PATH), config_dir)
    return AppConfig(
        chrome_user_data_dir=str(raw[_KEY_CHROME_USER_DATA_DIR]),
        chrome_profile=str(raw[_KEY_CHROME_PROFILE]),
        dry_run=bool(raw[_KEY_DRY_RUN]),
        input_csv=_resolve_path(raw[_KEY_INPUT_CSV], config_dir),
        mf_account=str(raw[_KEY_MF_ACCOUNT]),
        mapping_rules=mapping_rules,
        exclude_prefixes=raw.get(_KEY_EXCLUDE_PREFIXES)
        or list(AppConstants.DEFAULT_EXCLUDE_PREFIXES),
        gcloud_credentials_path=creds,
        duplicate_detection=dup,
        parser=parser,
        log_settings=log_settings,
        advanced=advanced,
    )
