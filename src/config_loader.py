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
_MSG_CONFIG_ROOT_TYPE = "config.yml のルート要素は object で指定してください。"
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

_MSG_MAPPING_RULES_TYPE = "mapping_rules は list で指定してください。"
_MSG_MAPPING_RULE_TYPE = "mapping_rules[{i}] は object で指定してください。"
_MSG_MAPPING_KEYWORD_EMPTY = "mapping_rules[{i}]: keyword が空です。"
_MSG_MAPPING_CATEGORY_EMPTY = "mapping_rules[{i}]: category が空です。"
_MSG_MAPPING_MATCH_MODE_INVALID = (
    "mapping_rules[{i}]: match_mode が無効です: {mode!r} （有効値: {valids}）"
)

_MSG_DUPLICATE_DETECTION_TYPE = "duplicate_detection は object で指定してください。"
_MSG_DUPLICATE_BACKEND_INVALID = (
    "duplicate_detection.backend が無効です: {value!r} （有効値: {valids}）"
)
_MSG_DUPLICATE_TOLERANCE_TYPE = (
    "duplicate_detection.tolerance_seconds には整数を指定してください。"
)
_MSG_DUPLICATE_TOLERANCE_RANGE = (
    "duplicate_detection.tolerance_seconds には 0 以上の整数を指定してください: {value}"
)

_MSG_PARSER_TYPE = "parser は object で指定してください。"
_MSG_PARSER_ENCODING_PRIORITY_TYPE = (
    "parser.encoding_priority は list で指定してください。"
)
_MSG_PARSER_ENCODING_PRIORITY_EMPTY = (
    "parser.encoding_priority は 1 件以上指定してください。"
)
_MSG_PARSER_ENCODING_PRIORITY_ITEM_TYPE = (
    "parser.encoding_priority[{i}] には文字列を指定してください。"
)
_MSG_PARSER_ENCODING_PRIORITY_ITEM_EMPTY = (
    "parser.encoding_priority[{i}] は空文字を許可しません。"
)
_MSG_PARSER_DATE_FORMATS_TYPE = "parser.date_formats は list で指定してください。"
_MSG_PARSER_DATE_FORMATS_EMPTY = "parser.date_formats は 1 件以上指定してください。"
_MSG_PARSER_DATE_FORMATS_ITEM_TYPE = (
    "parser.date_formats[{i}] には文字列を指定してください。"
)
_MSG_PARSER_DATE_FORMATS_ITEM_EMPTY = (
    "parser.date_formats[{i}] は空文字を許可しません。"
)

_MSG_LOG_SETTINGS_TYPE = "log_settings は object で指定してください。"
_MSG_LOG_MAX_LOG_COUNT_TYPE = "log_settings.max_log_count には整数を指定してください。"
_MSG_LOG_MAX_LOG_COUNT_RANGE = (
    "log_settings.max_log_count には 0 以上の整数を指定してください: {value}"
)
_MSG_LOG_MAX_TOTAL_LOG_SIZE_MB_TYPE = (
    "log_settings.max_total_log_size_mb には整数を指定してください。"
)
_MSG_LOG_MAX_TOTAL_LOG_SIZE_MB_RANGE = (
    "log_settings.max_total_log_size_mb には 0 以上の整数を指定してください: {value}"
)

_MSG_ADVANCED_TYPE = "advanced は object で指定してください。"
_MSG_ADV_SCREENSHOT_ON_ERROR_TYPE = (
    "advanced.screenshot_on_error には true または false を指定してください。"
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
        loaded = yaml.safe_load(f)

    if loaded is None:
        raw: dict = {}
    elif isinstance(loaded, dict):
        raw = loaded
    else:
        raise ValueError(_MSG_CONFIG_ROOT_TYPE)

    mapping_rules = _get_optional_list_section(
        raw,
        _KEY_MAPPING_RULES,
        _MSG_MAPPING_RULES_TYPE,
    )
    duplicate_detection = _get_optional_dict_section(
        raw,
        _KEY_DUPLICATE_DETECTION,
        _MSG_DUPLICATE_DETECTION_TYPE,
    )
    parser = _get_optional_dict_section(raw, _KEY_PARSER, _MSG_PARSER_TYPE)
    log_settings = _get_optional_dict_section(
        raw,
        _KEY_LOG_SETTINGS,
        _MSG_LOG_SETTINGS_TYPE,
    )
    advanced = _get_optional_dict_section(raw, _KEY_ADVANCED, _MSG_ADVANCED_TYPE)

    _validate_required(raw)
    _validate_mapping_rules(mapping_rules)
    _validate_duplicate_detection(duplicate_detection)
    _validate_parser(parser)
    _validate_log_settings(log_settings)
    _validate_advanced(advanced)
    _validate_paths(
        raw,
        skip_chrome_validation=raw[_KEY_DRY_RUN],
        config_dir=path.parent,
        advanced_raw=advanced,
    )
    _validate_gcloud(
        duplicate_detection,
        raw.get(_KEY_GCLOUD_CREDENTIALS_PATH),
        config_dir=path.parent,
    )
    return _build_config(
        raw,
        config_dir=path.parent,
        mapping_rules_raw=mapping_rules,
        duplicate_detection_raw=duplicate_detection,
        parser_raw=parser,
        log_settings_raw=log_settings,
        advanced_raw=advanced,
    )


def _get_optional_dict_section(raw: dict, key: str, error_message: str) -> dict:
    """任意の object セクションを取得し、型不正を検証する。"""
    value = raw.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(error_message)
    return value


def _get_optional_list_section(raw: dict, key: str, error_message: str) -> list:
    """任意の list セクションを取得し、型不正を検証する。"""
    value = raw.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(error_message)
    return value


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
    advanced_raw: dict,
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
        if not isinstance(rule, dict):
            errors.append(_MSG_MAPPING_RULE_TYPE.format(i=i))
            continue
        if not str(rule.get(_KEY_RULE_KEYWORD, AppConstants.EMPTY_STRING)).strip():
            errors.append(_MSG_MAPPING_KEYWORD_EMPTY.format(i=i))
        if not str(rule.get(_KEY_RULE_CATEGORY, AppConstants.EMPTY_STRING)).strip():
            errors.append(_MSG_MAPPING_CATEGORY_EMPTY.format(i=i))
        mode = rule.get(_KEY_RULE_MATCH_MODE, AppConstants.DEFAULT_MATCH_MODE)
        if mode not in AppConstants.VALID_MATCH_MODES:
            valids = ", ".join(sorted(AppConstants.VALID_MATCH_MODES))
            errors.append(
                _MSG_MAPPING_MATCH_MODE_INVALID.format(i=i, mode=mode, valids=valids),
            )
    if errors:
        raise ValueError("\n".join(errors))


def _validate_duplicate_detection(section: dict) -> None:
    """duplicate_detection セクションを検証する。"""
    errors: list[str] = []

    backend = section.get(_KEY_DD_BACKEND, AppConstants.DEFAULT_BACKEND)
    if backend not in {
        AppConstants.BACKEND_LOCAL,
        AppConstants.BACKEND_GCLOUD,
    }:
        valids = ", ".join(
            sorted({AppConstants.BACKEND_LOCAL, AppConstants.BACKEND_GCLOUD})
        )
        errors.append(
            _MSG_DUPLICATE_BACKEND_INVALID.format(value=backend, valids=valids)
        )

    tolerance = section.get(_KEY_DD_TOLERANCE_SECONDS)
    if tolerance is not None:
        _validate_non_negative_int(
            tolerance,
            type_message=_MSG_DUPLICATE_TOLERANCE_TYPE,
            range_message=_MSG_DUPLICATE_TOLERANCE_RANGE,
            errors=errors,
        )

    if errors:
        raise ValueError("\n".join(errors))


def _validate_parser(section: dict) -> None:
    """parser セクションを検証する。"""
    errors: list[str] = []

    encoding_priority = section.get(_KEY_PARSER_ENCODING_PRIORITY)
    if encoding_priority is not None:
        _validate_string_list(
            encoding_priority,
            list_type_message=_MSG_PARSER_ENCODING_PRIORITY_TYPE,
            empty_list_message=_MSG_PARSER_ENCODING_PRIORITY_EMPTY,
            item_type_message=_MSG_PARSER_ENCODING_PRIORITY_ITEM_TYPE,
            item_empty_message=_MSG_PARSER_ENCODING_PRIORITY_ITEM_EMPTY,
            errors=errors,
        )

    date_formats = section.get(_KEY_PARSER_DATE_FORMATS)
    if date_formats is not None:
        _validate_string_list(
            date_formats,
            list_type_message=_MSG_PARSER_DATE_FORMATS_TYPE,
            empty_list_message=_MSG_PARSER_DATE_FORMATS_EMPTY,
            item_type_message=_MSG_PARSER_DATE_FORMATS_ITEM_TYPE,
            item_empty_message=_MSG_PARSER_DATE_FORMATS_ITEM_EMPTY,
            errors=errors,
        )

    if errors:
        raise ValueError("\n".join(errors))


def _validate_log_settings(section: dict) -> None:
    """log_settings セクションを検証する。"""
    errors: list[str] = []

    max_log_count = section.get(_KEY_LOG_MAX_LOG_COUNT)
    if max_log_count is not None:
        _validate_non_negative_int(
            max_log_count,
            type_message=_MSG_LOG_MAX_LOG_COUNT_TYPE,
            range_message=_MSG_LOG_MAX_LOG_COUNT_RANGE,
            errors=errors,
        )

    max_total_log_size_mb = section.get(_KEY_LOG_MAX_TOTAL_LOG_SIZE_MB)
    if max_total_log_size_mb is not None:
        _validate_non_negative_int(
            max_total_log_size_mb,
            type_message=_MSG_LOG_MAX_TOTAL_LOG_SIZE_MB_TYPE,
            range_message=_MSG_LOG_MAX_TOTAL_LOG_SIZE_MB_RANGE,
            errors=errors,
        )

    if errors:
        raise ValueError("\n".join(errors))


def _validate_advanced(section: dict) -> None:
    """advanced セクションを検証する。"""
    screenshot_on_error = section.get(_KEY_ADV_SCREENSHOT_ON_ERROR)
    if screenshot_on_error is not None and not isinstance(screenshot_on_error, bool):
        raise ValueError(_MSG_ADV_SCREENSHOT_ON_ERROR_TYPE)


def _validate_non_negative_int(
    value: object,
    *,
    type_message: str,
    range_message: str,
    errors: list[str],
) -> None:
    """非負整数の型と範囲を検証する。"""
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(type_message)
        return
    if value < 0:
        errors.append(range_message.format(value=value))


def _validate_string_list(
    value: object,
    *,
    list_type_message: str,
    empty_list_message: str,
    item_type_message: str,
    item_empty_message: str,
    errors: list[str],
) -> None:
    """文字列 list の型と各要素を検証する。"""
    if not isinstance(value, list):
        errors.append(list_type_message)
        return
    if not value:
        errors.append(empty_list_message)
        return
    for i, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(item_type_message.format(i=i))
            continue
        if not item.strip():
            errors.append(item_empty_message.format(i=i))


def _validate_gcloud(
    duplicate_detection_raw: dict,
    credentials_raw: object,
    *,
    config_dir: Path,
) -> None:
    """gcloud バックエンド使用時の追加検証を行う。

    Args:
        raw: YAML から読み込んだ辞書。
        config_dir: config.yml が置かれたディレクトリ。

    Raises:
        ValueError: backend が "gcloud" なのに gcloud_credentials_path が
            未設定の場合、または認証情報ファイルが存在しない場合。
    """
    backend = duplicate_detection_raw.get(_KEY_DD_BACKEND, AppConstants.DEFAULT_BACKEND)
    creds = credentials_raw

    if backend == AppConstants.BACKEND_GCLOUD and not creds:
        raise ValueError(_MSG_GCLOUD_CREDS_REQUIRED)

    resolved_creds = _resolve_optional_path(creds, config_dir)
    if resolved_creds is not None and not resolved_creds.exists():
        raise ValueError(_MSG_GCLOUD_CREDS_NOT_EXIST.format(path=resolved_creds))


def _build_config(
    raw: dict,
    *,
    config_dir: Path,
    mapping_rules_raw: list,
    duplicate_detection_raw: dict,
    parser_raw: dict,
    log_settings_raw: dict,
    advanced_raw: dict,
) -> AppConfig:
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
        for r in mapping_rules_raw
    ]

    dup = DuplicateDetectionConfig(
        backend=duplicate_detection_raw.get(
            _KEY_DD_BACKEND,
            AppConstants.DEFAULT_BACKEND,
        ),
        tolerance_seconds=duplicate_detection_raw.get(
            _KEY_DD_TOLERANCE_SECONDS,
            _DEFAULT_TOLERANCE_SECONDS,
        ),
    )

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

    logs_dir_raw = log_settings_raw.get(_KEY_LOG_LOGS_DIR)
    log_settings = LogSettings(
        logs_dir=_resolve_optional_path(logs_dir_raw, config_dir),
        max_log_count=log_settings_raw.get(_KEY_LOG_MAX_LOG_COUNT),
        max_total_log_size_mb=log_settings_raw.get(_KEY_LOG_MAX_TOTAL_LOG_SIZE_MB),
    )

    advanced = AdvancedConfig(
        screenshot_on_error=advanced_raw.get(
            _KEY_ADV_SCREENSHOT_ON_ERROR,
            _DEFAULT_SCREENSHOT_ON_ERROR,
        ),
        mf_categories_path=_resolve_optional_path(
            advanced_raw.get(_KEY_ADV_MF_CATEGORIES_PATH),
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
