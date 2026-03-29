"""pyproject.toml の runtime dependencies を検証するテスト。"""

from __future__ import annotations

from pathlib import Path


def _read_project_dependencies(pyproject_path: Path) -> list[str]:
    lines = pyproject_path.read_text(encoding="utf-8").splitlines()
    in_project_section = False
    in_dependencies = False
    dependencies: list[str] = []

    for line in lines:
        stripped = line.strip()

        if stripped == "[project]":
            in_project_section = True
            continue

        if in_project_section and stripped.startswith("[") and stripped != "[project]":
            break

        if not in_project_section:
            continue

        if stripped == "dependencies = [":
            in_dependencies = True
            continue

        if not in_dependencies:
            continue

        if stripped == "]":
            break

        if stripped:
            dependencies.append(stripped.strip('",'))

    return dependencies


def test_pyproject_declares_typing_extensions_runtime_dependency() -> None:
    """typing_extensions が runtime dependency に含まれることを確認する。"""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"

    dependencies = _read_project_dependencies(pyproject_path)

    assert any(
        dependency.startswith("typing_extensions>=")
        for dependency in dependencies
    )
