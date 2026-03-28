"""mf_category_map モジュールのテスト。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.mf_category_map import load_mf_category_map

if TYPE_CHECKING:
    from pathlib import Path


def test_load_mf_category_map_uses_default_resource() -> None:
    """既定の同梱カテゴリマップを読み込めることを確認する。"""
    category_map = load_mf_category_map()

    assert category_map["食料品"] == "食費"
    assert category_map["情報サービス"] == "通信費"


def test_load_mf_category_map_uses_override_file(tmp_path: Path) -> None:
    """指定した YAML パスが既定リソースより優先されることを確認する。"""
    override_file = tmp_path / "override.yml"
    override_file.write_text(
        "middle_to_large:\n  食料品: 特別な支出\n",
        encoding="utf-8",
    )

    category_map = load_mf_category_map(override_file)

    assert category_map == {"食料品": "特別な支出"}


def test_load_mf_category_map_rejects_invalid_root(tmp_path: Path) -> None:
    """middle_to_large が mapping でない場合に ValueError が送出されることを確認する。"""
    invalid_file = tmp_path / "invalid.yml"
    invalid_file.write_text("middle_to_large: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="middle_to_large"):
        load_mf_category_map(invalid_file)


def test_load_mf_category_map_rejects_invalid_entry(tmp_path: Path) -> None:
    """空値を含むカテゴリマップを拒否することを確認する。"""
    invalid_file = tmp_path / "invalid_entry.yml"
    invalid_file.write_text("middle_to_large:\n  食料品: ''\n", encoding="utf-8")

    with pytest.raises(ValueError, match="空でない文字列"):
        load_mf_category_map(invalid_file)
