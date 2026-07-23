"""Golden Dataset test configuration.

Golden tests run against fixed reference inputs and compare outputs to saved baselines.
Use ``pytest tests/golden --update-golden`` to regenerate baselines.

Fixtures directory layout:
    tests/golden/fixtures/
        shots/          # short MP4 clips (10-30s) used as golden shots
        baselines/      # JSON reference outputs (transcript, vision analysis, etc.)

To add a new golden shot:
1. Place an MP4 file in tests/golden/fixtures/shots/
2. Run ``pytest tests/golden/test_asr_golden.py --update-golden``
   to generate the baseline transcript.
3. Commit both the fixture and the baseline.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SHOTS_DIR = FIXTURES_DIR / "shots"
BASELINES_DIR = FIXTURES_DIR / "baselines"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Regenerate golden baselines instead of comparing against them",
    )


@pytest.fixture(scope="session")
def update_golden(request: pytest.FixtureRequest) -> bool:
    """True when --update-golden flag is set; causes tests to write new baselines."""
    return bool(request.config.getoption("--update-golden", default=False))


@pytest.fixture(scope="session")
def golden_shot_paths() -> list[Path]:
    """Return all MP4 files in the fixtures/shots directory."""
    if not SHOTS_DIR.exists():
        return []
    return sorted(SHOTS_DIR.glob("*.mp4"))


def load_baseline(name: str) -> dict:
    """Load a JSON baseline file by name (without .json extension)."""
    path = BASELINES_DIR / f"{name}.json"
    if not path.exists():
        pytest.skip(f"Golden baseline missing: {path}. Run with --update-golden to create it.")
    return json.loads(path.read_text())


def save_baseline(name: str, data: dict) -> None:
    """Save a JSON baseline file."""
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    path = BASELINES_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
