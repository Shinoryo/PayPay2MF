"""config_loader モジュールのテスト。

対応テストケース:
    TC-01-01: 正常な設定ファイルの読み込み
    TC-01-02: chrome_user_data_dir 欠落
    TC-01-03: chrome_profile 欠落
    TC-01-04: dry_run 欠落
    TC-01-05: input_csv 欠落
    TC-01-06: mf_account 欠落
    TC-01-07: デフォルト値補完の確認
    TC-01-09: 存在しない chrome_user_data_dir のパス検証
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import yaml

from src.config_loader import load_config
from src.constants import AppConstants

_CONFIG_FILENAME = "config.yml"
_YAML_ENCODING = AppConstants.DEFAULT_TEXT_ENCODING
_DEFAULT_CHROME_PROFILE = "Default"
_DEFAULT_MF_ACCOUNT = "PayPay残高"
_INPUT_CSV_FILENAME = "test.csv"
_HEADER_LINE = "header\n"
_USER_DATA_DIRNAME = "User Data"
_OTHER_WORK_DIRNAME = "other-workdir"
_LOGS_DIRNAME = "custom-logs"
_CUSTOM_CATEGORIES_FILENAME = "custom_categories.yml"
_MISSING_CATEGORIES_FILENAME = "missing_categories.yml"
_GCLOUD_CREDENTIALS_FILENAME = "service-account.json"
_MISSING_PATH_NAME = "nonexistent"
_MISSING_PROFILE = "MissingProfile"
_MATCH_MODE_INVALID = "fuzzy"

if TYPE_CHECKING:
    from pathlib import Path


def _write_config(tmp_path: Path, data: dict) -> Path:
    """テスト用に tmp_path へ YAML 設定ファイルを書き出す。

    Args:
        tmp_path: pytest の tmp_path フィクスチャ。
        data: 設定データの辞書。

    Returns:
        書き出した設定ファイルの Path。
    """
    config_file = tmp_path / _CONFIG_FILENAME
    config_file.write_text(
        yaml.dump(data, allow_unicode=True), encoding=_YAML_ENCODING,
    )
    return config_file


def _base_data(tmp_path: Path) -> dict:
    """最小有効設定データの辞書を生成する。

    chrome_user_data_dir、chrome_profile、dry_run、input_csv、mf_accountの
    5 項目を含む辞書を返す。

    Args:
        tmp_path: pytest の tmp_path フィクスチャ。

    Returns:
        必須項目をすべて含む設定辞書。
    """
    user_data = tmp_path / _USER_DATA_DIRNAME
    user_data.mkdir()
    (user_data / _DEFAULT_CHROME_PROFILE).mkdir()
    csv_file = tmp_path / _INPUT_CSV_FILENAME
    csv_file.write_text(_HEADER_LINE, encoding=_YAML_ENCODING)
    return {
        "chrome_user_data_dir": str(user_data),
        "chrome_profile": _DEFAULT_CHROME_PROFILE,
        "dry_run": True,
        "input_csv": str(csv_file),
        "mf_account": _DEFAULT_MF_ACCOUNT,
    }


# TC-01-01: 正常ロード
def test_load_config_ok(tmp_path: Path) -> None:
    """TC-01-01: 正常な設定ファイルを load_config で読み込めることを確認する。"""
    data = _base_data(tmp_path)
    cfg_path = _write_config(tmp_path, data)
    config = load_config(cfg_path)
    assert config.dry_run is True
    assert config.input_csv == tmp_path / _INPUT_CSV_FILENAME
    assert config.mf_account == _DEFAULT_MF_ACCOUNT
    assert config.exclude_prefixes == list(AppConstants.DEFAULT_EXCLUDE_PREFIXES)


# TC-01-02: 必須項目欠落（chrome_user_data_dir）
def test_missing_chrome_user_data_dir(tmp_path: Path) -> None:
    """TC-01-02: chrome_user_data_dir 欠落時に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    del data["chrome_user_data_dir"]
    cfg_path = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="chrome_user_data_dir"):
        load_config(cfg_path)


# TC-01-03: 必須項目欠落（chrome_profile）
def test_missing_chrome_profile(tmp_path: Path) -> None:
    """TC-01-03: chrome_profile 欠落時に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    del data["chrome_profile"]
    cfg_path = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="chrome_profile"):
        load_config(cfg_path)


# TC-01-04: 必須項目欠落（dry_run）
def test_missing_dry_run(tmp_path: Path) -> None:
    """TC-01-04: dry_run 欠落時に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    del data["dry_run"]
    cfg_path = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="dry_run"):
        load_config(cfg_path)


# TC-01-05: 必須項目欠落（input_csv）
def test_missing_input_csv(tmp_path: Path) -> None:
    """TC-01-05: input_csv 欠落時に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    del data["input_csv"]
    cfg_path = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="input_csv"):
        load_config(cfg_path)


# TC-01-06: 必須項目欠落（mf_account）
def test_missing_mf_account(tmp_path: Path) -> None:
    """TC-01-06: mf_account 欠落時に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    del data["mf_account"]
    cfg_path = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="mf_account"):
        load_config(cfg_path)


# TC-01-07: logs_dir 未指定でデフォルト値補完
def test_defaults_applied(tmp_path: Path) -> None:
    """TC-01-07: 省略可能項目のデフォルト値が正しく補完されることを確認する。"""
    data = _base_data(tmp_path)
    cfg_path = _write_config(tmp_path, data)
    config = load_config(cfg_path)
    assert config.log_settings.logs_dir is None
    assert config.duplicate_detection.backend == AppConstants.DEFAULT_BACKEND
    assert config.parser.encoding_priority == list(AppConstants.DEFAULT_ENCODING_PRIORITY)
    assert config.advanced.screenshot_on_error is False
    assert config.advanced.mf_categories_path is None


def test_mf_categories_path_is_resolved_relative_to_config(tmp_path: Path) -> None:
    """advanced.mf_categories_path は config.yml 基準の相対パスとして解決されることを確認する。"""
    data = _base_data(tmp_path)
    categories_file = tmp_path / _CUSTOM_CATEGORIES_FILENAME
    categories_file.write_text("middle_to_large:\n  食料品: 食費\n", encoding=_YAML_ENCODING)
    data["advanced"] = {"mf_categories_path": _CUSTOM_CATEGORIES_FILENAME}

    config = load_config(_write_config(tmp_path, data))

    assert config.advanced.mf_categories_path == categories_file


def test_input_csv_is_resolved_relative_to_config_even_when_cwd_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """input_csv は config.yml 基準の相対パスとして解決され、実行 cwd に依存しないことを確認する。"""
    data = _base_data(tmp_path)
    data["input_csv"] = _INPUT_CSV_FILENAME
    other_dir = tmp_path / _OTHER_WORK_DIRNAME
    other_dir.mkdir()

    monkeypatch.chdir(other_dir)
    config = load_config(_write_config(tmp_path, data))

    assert config.input_csv == tmp_path / _INPUT_CSV_FILENAME


def test_missing_relative_input_csv_raises_value_error(tmp_path: Path) -> None:
    """input_csv に config.yml 基準の存在しない相対パスを指定した場合に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    data["input_csv"] = _MISSING_PATH_NAME + AppConstants.CSV_EXTENSION

    with pytest.raises(
        ValueError,
        match=re.escape(str(tmp_path / data["input_csv"])),
    ):
        load_config(_write_config(tmp_path, data))


def test_logs_dir_is_resolved_relative_to_config(tmp_path: Path) -> None:
    """log_settings.logs_dir は config.yml 基準の相対パスとして解決されることを確認する。"""
    data = _base_data(tmp_path)
    data["log_settings"] = {"logs_dir": _LOGS_DIRNAME}

    config = load_config(_write_config(tmp_path, data))

    assert config.log_settings.logs_dir == tmp_path / _LOGS_DIRNAME


def test_gcloud_credentials_path_is_resolved_relative_to_config(tmp_path: Path) -> None:
    """gcloud_credentials_path は config.yml 基準の相対パスとして解決されることを確認する。"""
    data = _base_data(tmp_path)
    credentials_file = tmp_path / _GCLOUD_CREDENTIALS_FILENAME
    credentials_file.write_text("{}", encoding=_YAML_ENCODING)
    data["duplicate_detection"] = {"backend": AppConstants.BACKEND_GCLOUD}
    data["gcloud_credentials_path"] = _GCLOUD_CREDENTIALS_FILENAME

    config = load_config(_write_config(tmp_path, data))

    assert config.gcloud_credentials_path == credentials_file


def test_missing_relative_gcloud_credentials_path_raises_value_error(
    tmp_path: Path,
) -> None:
    """gcloud_credentials_path に config.yml 基準の存在しない相対パスを指定した場合に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    data["duplicate_detection"] = {"backend": AppConstants.BACKEND_GCLOUD}
    data["gcloud_credentials_path"] = _GCLOUD_CREDENTIALS_FILENAME

    with pytest.raises(
        ValueError,
        match=re.escape(str(tmp_path / _GCLOUD_CREDENTIALS_FILENAME)),
    ):
        load_config(_write_config(tmp_path, data))


def test_absolute_paths_are_preserved(tmp_path: Path) -> None:
    """絶対パスで指定した設定値はそのまま保持されることを確認する。"""
    data = _base_data(tmp_path)
    logs_dir = tmp_path / _LOGS_DIRNAME
    credentials_file = tmp_path / _GCLOUD_CREDENTIALS_FILENAME
    credentials_file.write_text("{}", encoding=_YAML_ENCODING)
    data["log_settings"] = {"logs_dir": str(logs_dir)}
    data["duplicate_detection"] = {"backend": AppConstants.BACKEND_GCLOUD}
    data["gcloud_credentials_path"] = str(credentials_file)

    config = load_config(_write_config(tmp_path, data))

    assert config.input_csv == tmp_path / _INPUT_CSV_FILENAME
    assert config.log_settings.logs_dir == logs_dir
    assert config.gcloud_credentials_path == credentials_file


def test_missing_mf_categories_path_raises_value_error(tmp_path: Path) -> None:
    """advanced.mf_categories_path が存在しない場合に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    data["advanced"] = {"mf_categories_path": _MISSING_CATEGORIES_FILENAME}

    with pytest.raises(ValueError, match=r"advanced\.mf_categories_path"):
        load_config(_write_config(tmp_path, data))


# TC-01-09: 存在しない chrome_user_data_dir（本番実行）
def test_nonexistent_chrome_user_data_dir_when_not_dry_run(tmp_path: Path) -> None:
    """TC-01-09: dry_run=False で存在しない chrome_user_data_dir を指定した場合に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    data["dry_run"] = False
    data["chrome_user_data_dir"] = str(tmp_path / _MISSING_PATH_NAME)
    cfg_path = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="chrome_user_data_dir のパスが存在しません"):
        load_config(cfg_path)


def test_nonexistent_chrome_user_data_dir_is_allowed_in_dry_run(tmp_path: Path) -> None:
    """dry_run=True では存在しない chrome_user_data_dir を指定しても設定読み込みが成功することを確認する。"""
    data = _base_data(tmp_path)
    data["chrome_user_data_dir"] = str(tmp_path / _MISSING_PATH_NAME)
    cfg_path = _write_config(tmp_path, data)

    config = load_config(cfg_path)

    assert config.dry_run is True
    assert config.chrome_user_data_dir == str(tmp_path / _MISSING_PATH_NAME)


def test_nonexistent_chrome_profile_when_not_dry_run(tmp_path: Path) -> None:
    """dry_run=False で存在しない chrome_profile を指定した場合に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    data["dry_run"] = False
    data["chrome_profile"] = _MISSING_PROFILE
    cfg_path = _write_config(tmp_path, data)

    with pytest.raises(ValueError, match="chrome_profile のディレクトリが存在しません"):
        load_config(cfg_path)


def test_nonexistent_chrome_profile_is_allowed_in_dry_run(tmp_path: Path) -> None:
    """dry_run=True では存在しない chrome_profile を指定しても設定読み込みが成功することを確認する。"""
    data = _base_data(tmp_path)
    data["chrome_profile"] = _MISSING_PROFILE
    cfg_path = _write_config(tmp_path, data)

    config = load_config(cfg_path)

    assert config.dry_run is True
    assert config.chrome_profile == _MISSING_PROFILE


# dry_run の型不正
def test_dry_run_type_error(tmp_path: Path) -> None:
    """dry_run に真偽値以外の型（文字列）を指定した場合に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    data["dry_run"] = "yes"
    cfg_path = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="dry_run"):
        load_config(cfg_path)


# mapping_rules バリデーション: keyword 空
def test_mapping_rule_empty_keyword(tmp_path: Path) -> None:
    """mapping_rules の keyword が空文字の場合に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    data["mapping_rules"] = [{"keyword": "", "category": "コンビニ"}]
    cfg_path = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="keyword"):
        load_config(cfg_path)


# mapping_rules バリデーション: 無効な match_mode
def test_mapping_rule_invalid_match_mode(tmp_path: Path) -> None:
    """mapping_rules の match_mode に無効な値を指定した場合に ValueError が送出されることを確認する。"""
    data = _base_data(tmp_path)
    data["mapping_rules"] = [
        {
            "keyword": "test",
            "category": "コンビニ",
            "match_mode": _MATCH_MODE_INVALID,
        },
    ]
    cfg_path = _write_config(tmp_path, data)
    with pytest.raises(ValueError, match="match_mode"):
        load_config(cfg_path)
