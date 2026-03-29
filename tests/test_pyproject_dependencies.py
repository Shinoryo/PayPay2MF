"""pyproject.toml の runtime dependencies を検証するテスト。"""

from __future__ import annotations

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


def test_pyproject_packages_console_script_modules_for_regular_install() -> None:
    """通常の wheel install でも console script の参照先モジュールが同梱されることを確認する。"""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"

    pyproject = _load_pyproject(pyproject_path)
    tool = pyproject["tool"]

    assert isinstance(tool, dict)
    setuptools = tool["setuptools"]
    assert isinstance(setuptools, dict)
    assert setuptools["packages"] == ["src"]
    assert setuptools["py-modules"] == ["main", "firestore_backfill"]
