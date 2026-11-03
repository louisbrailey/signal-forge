"""Render the optional forward template separately from installable services."""

import plistlib
from pathlib import Path

from tests.support import REPO_ROOT


def test_funded_template_renders_as_isolated_periodic_agent(tmp_path):
    template = REPO_ROOT / "deploy/launchd/templates/com.signalforge.funded-validation.plist"
    raw = template.read_text()
    paths = {
        "__CHECKOUT__": str(tmp_path / "pinned-checkout"),
        "__STUDY_ROOT__": str(tmp_path / "independent-study"),
        "__ENV_FILE__": str(tmp_path / "config/.env"),
    }
    for token, value in paths.items():
        assert token in raw
        raw = raw.replace(token, value)
    assert "__" not in raw
    data = plistlib.loads(raw.encode())
    checkout = Path(paths["__CHECKOUT__"])
    study = Path(paths["__STUDY_ROOT__"])
    assert data["Label"] == "com.signalforge.funded-validation"
    assert data["ProgramArguments"] == [
        str(checkout / ".venv/bin/python"),
        str(checkout / "scripts/funded_forward.py"),
        "collect",
        str(study),
        "--env-file",
        paths["__ENV_FILE__"],
    ]
    assert data["WorkingDirectory"] == str(checkout)
    assert data["EnvironmentVariables"]["PYTHONPATH"] == str(checkout / "src")
    assert data["EnvironmentVariables"]["PATH"].split(":")[0] == str(checkout / ".venv/bin")
    assert data["RunAtLoad"] is True
    assert data.get("KeepAlive", False) is False
    assert data["StartInterval"] == 1800
    for key in ("StandardOutPath", "StandardErrorPath"):
        assert Path(data[key]).is_absolute()
        assert Path(data[key]).parent == study
    assert "API_KEY" not in raw
    assert "WEBHOOK" not in raw
    assert not study.exists()  # static check: no actual study or provider calls
