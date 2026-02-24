"""Card visualization rendering via Blender subprocess or LuxCore direct.

Two render paths:
  1. Blender: subprocess invocation with --background (legacy, GPU via Cycles)
  2. LuxCore: direct pyluxcore API, no subprocess (preferred for glass/caustics)

The pipeline:
  Blender path:
    CardVizData -> JSON -> blender --background --python render_card.py -> PNG
  LuxCore path:
    CardVizData -> expand_grammar -> meshgen -> pyluxcore.Scene -> PNG
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

from .data import CardVizData

logger = logging.getLogger(__name__)

# Paths relative to this module
_VIZ_DIR = Path(__file__).parent
_SCRIPTS_DIR = _VIZ_DIR / "scripts"
_TEMPLATES_DIR = _VIZ_DIR / "templates"

RENDER_SCRIPT = _SCRIPTS_DIR / "render_card.py"
TEMPLATE_BLEND = _TEMPLATES_DIR / "recursive_glass.blend"

# Render timeout (seconds)
RENDER_TIMEOUT = 300

# Resolution variants for multi-resolution rendering
CARD_VARIANTS: dict[str, tuple[int, int]] = {
    "display": (1400, 300),
    "og": (1200, 630),
}


async def render_card(
    viz_data: CardVizData,
    output_path: Path | None = None,
    *,
    timeout: int = RENDER_TIMEOUT,
    template: Path | None = None,
    resolution: tuple[int, int] = (1400, 600),
    gpu_id: int | None = None,
) -> Path:
    """Render a single card visualization via Blender subprocess.

    Args:
        viz_data: Mathematical features for the card
        output_path: Where to write the PNG. If None, uses a temp directory.
        timeout: Max seconds for Blender process
        template: Override .blend template file
        gpu_id: Restrict Blender to this GPU via CUDA_VISIBLE_DEVICES.
                If None, Blender uses all visible GPUs.

    Returns:
        Path to rendered PNG

    Raises:
        RuntimeError: On render failure (#VIZ.00000001.RENDERFAIL),
                      missing output (#VIZ.00000002.NOOUTPUT),
                      missing Blender (#VIZ.00000003.BLENDERMISSING),
                      or timeout (#VIZ.00000006.TIMEOUT)
    """
    # Verify blender is available
    blender_path = shutil.which("blender")
    if blender_path is None:
        raise RuntimeError(
            "Blender not found in PATH.\n"
            "  #VIZ.00000003.BLENDERMISSING\n"
            "  Fix: Ensure devenv shell is active (blender is in devenv.nix packages)"
        )

    template_file = template or TEMPLATE_BLEND
    script_file = RENDER_SCRIPT

    if not script_file.exists():
        raise RuntimeError(
            f"Render script not found: {script_file}\n"
            "  #VIZ.00000001.RENDERFAIL"
        )

    # Create temp directory for input/output
    with tempfile.TemporaryDirectory(prefix="gaius-viz-") as tmp_dir:
        tmp = Path(tmp_dir)
        input_json = tmp / "input.json"
        tmp_output = tmp / "output.png"

        # Serialize viz data
        viz_data.to_json(input_json)

        # Build command
        cmd = [
            blender_path,
            "--background",
        ]

        # Only use template if it exists (script can create scene procedurally)
        if template_file.exists():
            cmd.append(str(template_file))

        cmd.extend([
            "--python", str(script_file),
            "--",  # Separator for script args
            "--input", str(input_json),
            "--output", str(tmp_output),
            "--width", str(resolution[0]),
            "--height", str(resolution[1]),
        ])

        if gpu_id is not None:
            logger.info(
                f"Rendering card {viz_data.card_id} on GPU {gpu_id}: "
                f"κ={viz_data.curvature:.2f} π={viz_data.persistence:.2f} "
                f"b1={viz_data.b1} b2={viz_data.b2}"
            )
        else:
            logger.info(
                f"Rendering card {viz_data.card_id}: "
                f"κ={viz_data.curvature:.2f} π={viz_data.persistence:.2f} "
                f"b1={viz_data.b1} b2={viz_data.b2}"
            )

        # Build environment: restrict to specific GPU if requested
        import os
        env = os.environ.copy()
        if gpu_id is not None:
            env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(
                f"Blender render timed out after {timeout}s for card {viz_data.card_id}.\n"
                "  #VIZ.00000006.TIMEOUT\n"
                "  Try: Increase timeout or simplify scene complexity"
            )

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            # Extract last 20 lines for diagnostics
            err_lines = stderr_text.strip().split("\n")[-20:]
            raise RuntimeError(
                f"Blender render failed (exit code {proc.returncode}) "
                f"for card {viz_data.card_id}.\n"
                "  #VIZ.00000001.RENDERFAIL\n"
                f"  stderr (last 20 lines):\n"
                + "\n".join(f"    {line}" for line in err_lines)
            )

        # Check output exists
        if not tmp_output.exists():
            raise RuntimeError(
                f"Blender completed but no image produced for card {viz_data.card_id}.\n"
                "  #VIZ.00000002.NOOUTPUT\n"
                f"  stdout: {stdout_text[:500]}"
            )

        # Move to final location
        if output_path is None:
            output_path = Path(tempfile.mkdtemp(prefix="gaius-viz-out-")) / f"{viz_data.card_id}.png"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_output, output_path)

        file_size = output_path.stat().st_size
        logger.info(
            f"Rendered {viz_data.card_id} → {output_path} ({file_size / 1024:.1f} KB)"
        )

        return output_path


async def render_batch(
    cards: list[CardVizData],
    output_dir: Path | None = None,
    *,
    concurrency: int = 4,
    timeout: int = RENDER_TIMEOUT,
) -> list[Path]:
    """Render multiple cards with bounded concurrency.

    Args:
        cards: List of CardVizData to render
        output_dir: Directory for output PNGs. If None, uses temp dir.
        concurrency: Max parallel Blender processes
        timeout: Per-card render timeout

    Returns:
        List of output PNG paths (same order as input)
    """
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="gaius-viz-batch-"))
    output_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(concurrency)
    results: list[Path | Exception] = [Exception("not started")] * len(cards)

    async def _render_one(idx: int, viz_data: CardVizData) -> None:
        async with semaphore:
            out_path = output_dir / f"{viz_data.card_id}.png"
            try:
                result = await render_card(viz_data, out_path, timeout=timeout)
                results[idx] = result
            except Exception as e:
                logger.error(f"Failed to render card {viz_data.card_id}: {e}")
                results[idx] = e

    tasks = [_render_one(i, card) for i, card in enumerate(cards)]
    await asyncio.gather(*tasks)

    # Collect successful renders, raise on total failure
    paths: list[Path] = []
    failures = 0
    for r in results:
        if isinstance(r, Path):
            paths.append(r)
        else:
            failures += 1

    logger.info(
        f"Batch render complete: {len(paths)} succeeded, {failures} failed"
    )

    return paths


async def render_card_variants(
    viz_data: CardVizData,
    output_dir: Path,
    *,
    variants: dict[str, tuple[int, int]] | None = None,
    timeout: int = RENDER_TIMEOUT,
    gpu_id: int | None = None,
) -> dict[str, Path]:
    """Render a card at multiple resolution variants.

    Args:
        viz_data: Mathematical features for the card
        output_dir: Directory for output PNGs (creates {variant}.png files)
        variants: Resolution variants to render. Defaults to CARD_VARIANTS.
        timeout: Per-variant render timeout
        gpu_id: Restrict Blender to this GPU via CUDA_VISIBLE_DEVICES.

    Returns:
        Dict mapping variant name to rendered PNG path
    """
    if variants is None:
        variants = CARD_VARIANTS

    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Path] = {}

    for variant_name, (width, height) in variants.items():
        output_path = output_dir / f"{variant_name}.png"
        logger.info(
            f"Rendering {viz_data.card_id} variant={variant_name} "
            f"({width}x{height})"
        )
        result = await render_card(
            viz_data,
            output_path,
            timeout=timeout,
            resolution=(width, height),
            gpu_id=gpu_id,
        )
        results[variant_name] = result

    return results


# ---------------------------------------------------------------------------
# LuxCore render path (no Blender subprocess needed)
# ---------------------------------------------------------------------------

# Default LuxCore halt conditions
LUXCORE_HALT_TIME = 60      # seconds
LUXCORE_HALT_SAMPLES = 512  # samples per pixel


async def render_card_luxcore_async(
    viz_data: CardVizData,
    output_path: Path | None = None,
    *,
    resolution: tuple[int, int] = (1400, 600),
    halt_time: int = LUXCORE_HALT_TIME,
    halt_samples: int = LUXCORE_HALT_SAMPLES,
    gpu_id: int | None = None,
) -> Path:
    """Render a single card visualization via LuxCore (async wrapper).

    Runs the synchronous LuxCore render in a thread pool executor to
    avoid blocking the event loop.

    Args:
        viz_data: Mathematical features for the card.
        output_path: Where to write the PNG. If None, uses a temp directory.
        resolution: (width, height) in pixels.
        halt_time: Max render time in seconds.
        halt_samples: Max samples per pixel.
        gpu_id: Restrict rendering to this physical GPU index.

    Returns:
        Path to rendered PNG.
    """
    from .luxcore_renderer import render_card_luxcore

    if output_path is None:
        output_path = Path(tempfile.mkdtemp(prefix="gaius-viz-lux-")) / f"{viz_data.card_id}.png"

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: render_card_luxcore(
            viz_data,
            output_path,
            resolution=resolution,
            halt_time=halt_time,
            halt_samples=halt_samples,
            gpu_id=gpu_id,
        ),
    )
    return result


async def render_card_variants_luxcore(
    viz_data: CardVizData,
    output_dir: Path,
    *,
    variants: dict[str, tuple[int, int]] | None = None,
    halt_time: int = LUXCORE_HALT_TIME,
    halt_samples: int = LUXCORE_HALT_SAMPLES,
    gpu_id: int | None = None,
) -> dict[str, Path]:
    """Render a card at multiple resolution variants via LuxCore.

    Args:
        viz_data: Mathematical features for the card.
        output_dir: Directory for output PNGs (creates {variant}.png files).
        variants: Resolution variants to render. Defaults to CARD_VARIANTS.
        halt_time: Max render time per variant.
        halt_samples: Max samples per pixel per variant.
        gpu_id: Restrict rendering to this physical GPU index.

    Returns:
        Dict mapping variant name to rendered PNG path.
    """
    if variants is None:
        variants = CARD_VARIANTS

    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Path] = {}

    for variant_name, (width, height) in variants.items():
        output_path = output_dir / f"{variant_name}.png"
        logger.info(
            f"LuxCore rendering {viz_data.card_id} variant={variant_name} "
            f"({width}x{height})"
        )
        result = await render_card_luxcore_async(
            viz_data,
            output_path,
            resolution=(width, height),
            halt_time=halt_time,
            halt_samples=halt_samples,
            gpu_id=gpu_id,
        )
        results[variant_name] = result

    return results
