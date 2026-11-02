"""Refuse Chromium 156 before it can make a web request.

Chrome/Chromium 156 (stable October 2026) shipped with a large set of
memory-corruption bugs. Builds before 156.0.8078.73 are also missing the
fix for CVE-2026-118306, a FileSystem sandbox escape. The whole milestone
stays suspended: that browser must not load a page on this machine.

Other milestones are not this hold. ``--version`` does not navigate.
Local cognition does not launch a browser and is unaffected.
"""

from __future__ import annotations

import os
import re
import subprocess

CHROMIUM_156_GURU = "#BR.00000001.CHROMIUM156"
_HELD_MAJOR = 156
_VERSION_RE = re.compile(r"(?:Chromium|Chrome)(?: for Testing)?\s+(\d+)\.\d+")
_PATH_RE = re.compile(r"chrom(?:e|ium)[^\n]*?(\d+)\.\d+\.\d+\.\d+")


def major_from_version_text(text: str) -> int | None:
    """Major milestone from ``chromium --version``, or None."""
    match = _VERSION_RE.search(text or "")
    if match:
        return int(match.group(1))
    return None


def major_from_path(path: str) -> int | None:
    """Major milestone baked into a Nix store path, or None."""
    match = _PATH_RE.search(path or "")
    if match:
        return int(match.group(1))
    return None


def refusal_reason(binary: str, version_text: str = "") -> str | None:
    """Guru message when this binary must not start, else None."""
    path_major = major_from_path(binary)
    text_major = major_from_version_text(version_text)
    if path_major != _HELD_MAJOR and text_major != _HELD_MAJOR:
        return None
    shown = (version_text or binary).strip().splitlines()
    detail = shown[0] if shown else binary
    return (
        f"{CHROMIUM_156_GURU} refusing to launch Chromium 156 ({detail}).\n"
        "  Web requests through this browser are suspended.\n"
        "  Local cognition cycles do not use Chromium and stay enabled."
    )


def chromium_version_text(binary: str, *, timeout: float = 15.0) -> str:
    """Run ``binary --version``. This does not open a page.

    ``LD_LIBRARY_PATH`` from a devenv shell can point Playwright's Chrome
    at a libxcb that needs glibc 2.38, so ``--version`` prints a linker
    error instead of the milestone. Drop that path for the probe only.
    """
    env = os.environ.copy()
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    proc = subprocess.run(
        [binary, "--version"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    return f"{proc.stdout or ''}\n{proc.stderr or ''}"


def refuse_chromium_156(binary: str) -> None:
    """Raise before a Chromium 156 process is started.

    Call this on the resolved binary. Do not exec that binary with a
    URL, and do not hand it to Selenium or Playwright, when this raises.
    A binary whose milestone cannot be read is refused too: an install
    or a broken ``--version`` must not slip a 156 browser through.
    """
    text = ""
    try:
        text = chromium_version_text(binary)
    except (OSError, subprocess.TimeoutExpired):
        text = ""
    reason = refusal_reason(binary, text)
    if reason:
        raise RuntimeError(reason)
    if major_from_version_text(text) is None and major_from_path(binary) is None:
        raise RuntimeError(
            f"{CHROMIUM_156_GURU} refusing to launch {binary}: could not read "
            "a Chromium milestone before a web request.\n"
            "  Chromium 156 stays suspended until the binary reports another major."
        )


def checked_playwright_chromium(playwright: object) -> str:
    """Version-check Playwright's Chromium, and refuse a missing binary.

    A missing browser must not fall through to ``playwright install``:
    that download can fetch Chromium 156 and then open a page.
    """
    chromium = getattr(playwright, "chromium", None)
    exe = getattr(chromium, "executable_path", None)
    if not exe or not os.path.isfile(str(exe)):
        raise RuntimeError(
            f"{CHROMIUM_156_GURU} refusing to launch Chromium: no binary was "
            "available to version-check, so an install could fetch Chromium 156.\n"
            "  Point the launcher at a Chromium whose major version is not 156."
        )
    refuse_chromium_156(str(exe))
    return str(exe)
