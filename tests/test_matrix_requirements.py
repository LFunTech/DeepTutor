"""Tests for the pinned Matrix dependency split."""

from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def _extras() -> dict[str, list[str]]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]


def test_matrix_default_requirements_pin_non_e2e_nio() -> None:
    text = (ROOT / "requirements" / "matrix.txt").read_text(encoding="utf-8")

    assert "matrix-nio[e2e]" not in text
    assert "matrix-nio==0.26.0" in text
    assert "matrix-nio==0.26.0" in _extras()["matrix"]


def test_matrix_e2e_requirements_pin_crypto_binding_without_python_olm() -> None:
    text = (ROOT / "requirements" / "matrix-e2e.txt").read_text(encoding="utf-8")
    matrix_e2e = _extras()["matrix-e2e"]

    assert "-r matrix.txt" in text
    assert "matrix-nio[e2e]==0.26.0" in text
    assert "vodozemac==0.10.0" in text
    requirement_lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    assert all(not line.startswith("python-olm") for line in requirement_lines)
    assert "matrix-nio[e2e]==0.26.0" in matrix_e2e
    assert "vodozemac==0.10.0" in matrix_e2e
