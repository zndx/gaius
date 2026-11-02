"""Chromium 156 is refused before any page load. Other milestones pass."""

from __future__ import annotations

import os
import stat

import pytest

from gaius.core.chromium_hold import (
    CHROMIUM_156_GURU,
    major_from_path,
    major_from_version_text,
    refuse_chromium_156,
    refusal_reason,
)


def test_version_text_majors():
    assert major_from_version_text("Chromium 144.0.7559.109") == 144
    assert major_from_version_text("Google Chrome for Testing 147.0.7727.15") == 147
    assert major_from_version_text("Chromium 156.0.8078.47") == 156
    assert major_from_version_text("Google Chrome 156.0.8078.73") == 156
    assert major_from_version_text("") is None


def test_store_path_major():
    path = "/nix/store/abc-chromium-144.0.7559.109/bin/chromium"
    assert major_from_path(path) == 144
    assert major_from_path("/nix/store/abc-chromium-156.0.8078.47/bin/chromium") == 156
    assert major_from_path("/home/rch/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome") is None


def test_refusal_is_only_milestone_156():
    assert refusal_reason("/bin/chromium", "Chromium 144.0.7559.109") is None
    assert refusal_reason("/bin/chromium", "Google Chrome for Testing 147.0.7727.15") is None
    reason = refusal_reason("/bin/chromium", "Chromium 156.0.8078.73")
    assert reason is not None
    assert reason.startswith(CHROMIUM_156_GURU)
    path_reason = refusal_reason(
        "/nix/store/abc-chromium-156.0.8078.47/bin/chromium",
        "",
    )
    assert path_reason is not None
    assert CHROMIUM_156_GURU in path_reason


def _fake_chromium(tmp_path, name: str, script: str) -> str:
    binary = tmp_path / name
    binary.write_text(script)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    return str(binary)


def test_refuse_executes_only_version_check(tmp_path):
    binary = _fake_chromium(
        tmp_path,
        "chromium",
        "#!/bin/sh\necho 'Chromium 156.0.8078.47'\n",
    )
    with pytest.raises(RuntimeError, match="CHROMIUM156"):
        refuse_chromium_156(binary)


def test_allow_other_milestone(tmp_path):
    binary = _fake_chromium(
        tmp_path,
        "chromium",
        "#!/bin/sh\necho 'Chromium 144.0.7559.109'\n",
    )
    refuse_chromium_156(binary)


def test_store_path_156_refused_when_version_fails(tmp_path):
    folder = tmp_path / "chromium-156.0.8078.47" / "bin"
    folder.mkdir(parents=True)
    binary = _fake_chromium(folder, "chromium", "#!/bin/sh\nexit 1\n")
    with pytest.raises(RuntimeError, match="CHROMIUM156"):
        refuse_chromium_156(binary)


def test_unreadable_milestone_is_refused(tmp_path):
    binary = _fake_chromium(tmp_path, "chrome", "#!/bin/sh\necho linker-error\nexit 1\n")
    with pytest.raises(RuntimeError, match="CHROMIUM156"):
        refuse_chromium_156(binary)


def test_installed_chromium_is_not_156():
    """The browser on PATH is not the suspended milestone."""
    import shutil

    binary = shutil.which("chromium")
    if not binary or not os.path.isfile(binary):
        pytest.skip("no chromium on PATH")
    refuse_chromium_156(binary)
