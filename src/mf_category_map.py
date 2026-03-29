"""Money Forward カテゴリマップの読み込み。"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

_DEFAULT_MF_CATEGORIES_PATH = Path(__file__).with_name("mf_categories.yml")
_ROOT_KEY = "middle_to_large"

_MSG_CATEGORY_MAP_NOT_FOUND = "MF カテゴリマップが見つかりません: {path}"
_MSG_CATEGORY_MAP_ROOT_INVALID = (
    "MF カテゴリマップ YAML の middle_to_large は mapping である必要があります: {path}"
)
_MSG_CATEGORY_MAP_EMPTY = "MF カテゴリマップが空です: {path}"
_MSG_CATEGORY_MAP_ENTRY_INVALID = (
    "MF カテゴリマップには空でない文字列のキーと値を"
    "指定してください: {key!r} -> {value!r}"
)


def load_mf_category_map(path: Path | None = None) -> dict[str, str]:
    """Money Forward カテゴリマップを読み込む。"""
    resolved_path = (
        path.resolve()
        if path is not None
        else _DEFAULT_MF_CATEGORIES_PATH.resolve()
    )
    return dict(_load_mf_category_map(resolved_path))


@cache
def _load_mf_category_map(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(_MSG_CATEGORY_MAP_NOT_FOUND.format(path=path))

    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    mapping = raw.get(_ROOT_KEY)
    if not isinstance(mapping, dict):
        raise TypeError(_MSG_CATEGORY_MAP_ROOT_INVALID.format(path=path))

    normalized: dict[str, str] = {}
    for key, value in mapping.items():
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            or not value
        ):
            raise ValueError(
                _MSG_CATEGORY_MAP_ENTRY_INVALID.format(key=key, value=value),
            )
        normalized[key] = value

    if not normalized:
        raise ValueError(_MSG_CATEGORY_MAP_EMPTY.format(path=path))

    return normalized
