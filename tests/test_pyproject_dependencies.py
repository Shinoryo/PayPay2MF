"""pyproject.toml の runtime dependencies を検証するテスト。"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path


def _load_pyproject(pyproject_path: Path) -> dict[str, object]:
    return tomllib.loads(pyproject_path.read_text(encoding="utf-8"))


def test_pyproject_requires_python_3_11_or_newer() -> None:
    """サポート対象の最小 Python バージョンが 3.11 であることを確認する。"""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"

    pyproject = _load_pyproject(pyproject_path)
    project = pyproject["project"]

    assert isinstance(project, dict)
    assert project["requires-python"] == ">=3.11"


def test_pyproject_does_not_declare_typing_extensions_runtime_dependency() -> None:
    """Python 3.11 以降では typing_extensions を runtime dependency に含めない。"""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"

    pyproject = _load_pyproject(pyproject_path)
    project = pyproject["project"]

    assert isinstance(project, dict)
    dependencies = project["dependencies"]

    assert isinstance(dependencies, list)
    assert all(
        not dependency.startswith("typing_extensions") for dependency in dependencies
    )


def test_pyproject_declares_mit_license_and_license_file() -> None:
    """配布メタデータに MIT ライセンスと LICENSE 同梱設定があることを確認する。"""
    repo_root = Path(__file__).resolve().parents[1]
    pyproject_path = repo_root / "pyproject.toml"
    pyproject = _load_pyproject(pyproject_path)
    project = pyproject["project"]
    tool = pyproject["tool"]

    assert isinstance(project, dict)
    assert isinstance(tool, dict)
    setuptools = tool["setuptools"]

    assert isinstance(setuptools, dict)

    assert project["license"] == "MIT"
    assert setuptools["license-files"] == ["LICENSE"]
    assert (repo_root / "LICENSE").exists()


def test_pyproject_packages_paypay2mf_namespace_for_regular_install() -> None:
    """通常の wheel install でも paypay2mf 名前空間が同梱されることを確認する。"""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"

    pyproject = _load_pyproject(pyproject_path)
    tool = pyproject["tool"]
    project = pyproject["project"]

    assert isinstance(tool, dict)
    assert isinstance(project, dict)
    setuptools = tool["setuptools"]
    assert isinstance(setuptools, dict)
    package_data = setuptools["package-data"]
    assert isinstance(package_data, dict)

    assert setuptools["package-dir"] == {"": "src"}
    assert setuptools["packages"] == ["paypay2mf"]
    assert "py-modules" not in setuptools
    assert package_data["paypay2mf"] == ["mf_categories.yml"]
    assert project["scripts"] == {
        "paypay2mf": "paypay2mf.cli:main",
        "paypay2mf-firestore-backfill": "paypay2mf.firestore_backfill:main",
    }


def test_runtime_import_uses_paypay2mf_namespace() -> None:
    """ソースチェックアウト上でも paypay2mf パッケージを import できることを確認する。"""
    package = importlib.import_module("paypay2mf")
    category_module = importlib.import_module("paypay2mf.mf_category_map")

    assert package.__file__ is not None
    assert category_module.__file__ is not None


def test_pyproject_dev_dependencies_include_quality_gates() -> None:
    """dev extra に品質ゲート再現用ツールが含まれることを確認する。"""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"

    pyproject = _load_pyproject(pyproject_path)
    project = pyproject["project"]

    assert isinstance(project, dict)
    optional_dependencies = project["optional-dependencies"]
    assert isinstance(optional_dependencies, dict)
    dev_dependencies = optional_dependencies["dev"]
    assert isinstance(dev_dependencies, list)

    assert any(dependency.startswith("pytest>=") for dependency in dev_dependencies)
    assert any(
        dependency.startswith("pytest-mock>=") for dependency in dev_dependencies
    )
    assert any(dependency.startswith("ruff>=") for dependency in dev_dependencies)
    assert any(dependency.startswith("pip-audit>=") for dependency in dev_dependencies)
