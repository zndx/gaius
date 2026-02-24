"""LuxCore direct renderer for card visualizations.

Builds scenes directly via pyluxcore API -- no Blender subprocess needed.
The grammar engine's shape list feeds into LuxCore as inline meshes with
physically-based glass, emission, and glossy materials.

Render pipeline:
    CardVizData -> expand_grammar() -> meshgen -> pyluxcore.Scene -> PNG

LuxCore advantages over Blender Cycles for this use case:
  - True spectral glass with proper caustics (no opaque white blobs)
  - Homogeneous volume absorption for amber/blue tinting
  - Direct Python API (no subprocess overhead)

Render config:
  - PATHOCL engine when CUDA GPUs detected, PATHCPU fallback
  - SOBOL sampler for low-discrepancy convergence
  - GPU device selection filters to CUDA devices (skips OpenCL duplicates)
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from .data import CardVizData
from .grammar import (
    CORE,
    FILAMENT,
    PETAL,
    SHELL,
    TORUS,
    VOID,
    expand_grammar,
)
from .meshgen import (
    apply_transform,
    compute_normals,
    make_cylinder,
    make_ico_sphere,
    make_petal_disk,
    make_torus,
)

logger = logging.getLogger(__name__)

_LUXCORE_INITIALIZED = False


def _ensure_luxcore():
    """Import and initialize pyluxcore (once per process).

    Prefers the from-source GPU build at thirdparty/installed/LuxCore/ over the
    PyPI CPU-only wheel.  Calls pyluxcore.Init() to initialize CLEW/CUEW and
    enumerate GPU devices.  Subsequent calls return the cached module without
    re-initializing.
    """
    global _LUXCORE_INITIALIZED
    if not _LUXCORE_INITIALIZED:
        import sys

        # Prefer from-source GPU build over PyPI CPU-only wheel
        src_dir = Path(__file__).resolve().parents[3]  # repo root
        gpu_path = src_dir / "thirdparty" / "installed" / "LuxCore" / "pyluxcore"
        if gpu_path.is_dir():
            sys.path.insert(0, str(gpu_path))
            # Evict any cached CPU-only import
            sys.modules.pop("pyluxcore", None)

        try:
            import pyluxcore
        except ImportError as e:
            raise RuntimeError(
                "pyluxcore not installed.\n"
                "  #VIZ.00000007.NOLUXCORE\n"
                "  Fix: uv pip install pyluxcore --no-deps"
            ) from e

        pyluxcore.Init()
        devices = pyluxcore.GetOpenCLDeviceList()
        gpu_count = sum(1 for d in devices if "CUDA_GPU" in str(d))
        logger.info(
            f"pyluxcore {pyluxcore.Version()}: "
            f"{gpu_count} CUDA GPUs, {len(devices)} total devices"
        )
        _LUXCORE_INITIALIZED = True
    else:
        import pyluxcore

    return pyluxcore


def _curvature_color(curvature: float) -> tuple[float, float, float]:
    """Pale warm white <-> visible soft blue driven by curvature.

    Same mapping as the Blender path -- ensures visual consistency.
    """
    r = 0.85 - curvature * 0.42     # 0.85 -> 0.43
    g = 0.88 - curvature * 0.12     # 0.88 -> 0.76
    b = 0.92 + curvature * 0.08     # 0.92 -> 1.00
    return (r, g, b)


def render_card_luxcore(
    viz_data: CardVizData,
    output_path: str | Path,
    *,
    resolution: tuple[int, int] = (1400, 600),
    halt_time: int = 60,
    halt_samples: int = 512,
    gpu_id: int | None = None,
) -> Path:
    """Render a single card visualization via LuxCore.

    Args:
        viz_data: Mathematical features for the card.
        output_path: Where to write the PNG.
        resolution: (width, height) in pixels.
        halt_time: Max render time in seconds.
        halt_samples: Max samples per pixel.
        gpu_id: Restrict rendering to this physical GPU index. When set, only
                the corresponding CUDA device is selected (the orchestrator
                evicts vLLM endpoints from this GPU first).

    Returns:
        Path to rendered PNG.

    Raises:
        RuntimeError: If pyluxcore is not available (#VIZ.00000007.NOLUXCORE)
                      or render fails (#VIZ.00000008.LUXCOREFAIL).
    """
    pyluxcore = _ensure_luxcore()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    width, height = resolution
    data = asdict(viz_data)
    # Convert tuple back from list (asdict converts tuples to lists)
    if isinstance(data.get("gradient_direction"), list):
        data["gradient_direction"] = tuple(data["gradient_direction"])

    logger.info(
        f"LuxCore render {viz_data.card_id}: "
        f"k={viz_data.curvature:.2f} pi={viz_data.persistence:.2f} "
        f"b1={viz_data.b1} b2={viz_data.b2} "
        f"res={width}x{height} halt={halt_time}s/{halt_samples}spp"
    )

    # 1. Expand grammar
    shapes = expand_grammar(data)
    logger.info(f"  Grammar: {len(shapes)} shapes")

    # 2. Build scene
    scene = pyluxcore.Scene()
    props = pyluxcore.Properties()

    # Materials
    _add_materials(props, data)

    # Shapes and objects
    for idx, (shape_type, xf) in enumerate(shapes):
        _add_shape(props, scene, shape_type, xf, idx, data)

    # Floor
    _add_floor(props, scene)

    # Apply scene properties
    scene.Parse(props)

    # Lights and camera are part of the scene in LuxCore
    light_props = pyluxcore.Properties()
    _add_lights(light_props, data)
    _add_camera(light_props, width, height)
    scene.Parse(light_props)

    # 3. Render config (engine, film, halt conditions -- NOT scene elements)
    config_props = pyluxcore.Properties()
    # Select GPU engine when CUDA devices are available
    devices = pyluxcore.GetOpenCLDeviceList()
    cuda_indices = [i for i, d in enumerate(devices) if "CUDA_GPU" in str(d)]
    if cuda_indices:
        config_props.Set(pyluxcore.Property("renderengine.type", "PATHOCL"))
        if gpu_id is not None:
            # Use only the specific CUDA device matching the evicted GPU
            # CUDA devices appear after OpenCL devices in the list;
            # physical GPU N maps to cuda_indices[N]
            if gpu_id < len(cuda_indices):
                target_idx = cuda_indices[gpu_id]
                selection = "".join(
                    "1" if i == target_idx else "0"
                    for i in range(len(devices))
                )
            else:
                # Fallback: use last CUDA device
                selection = "".join(
                    "1" if i == cuda_indices[-1] else "0"
                    for i in range(len(devices))
                )
            config_props.Set(
                pyluxcore.Property("opencl.devices.select", selection)
            )
            logger.info(f"  Engine: PATHOCL (GPU {gpu_id})")
        else:
            # Use all CUDA devices
            selection = "".join(
                "1" if "CUDA_GPU" in str(d) else "0" for d in devices
            )
            config_props.Set(
                pyluxcore.Property("opencl.devices.select", selection)
            )
            logger.info(f"  Engine: PATHOCL ({len(cuda_indices)} CUDA devices)")
    else:
        config_props.Set(pyluxcore.Property("renderengine.type", "PATHCPU"))
        logger.info("  Engine: PATHCPU (no CUDA GPUs found)")
    config_props.Set(pyluxcore.Property("sampler.type", "SOBOL"))

    # Film
    config_props.Set(pyluxcore.Property("film.width", width))
    config_props.Set(pyluxcore.Property("film.height", height))

    # Outputs
    config_props.Set(pyluxcore.Property("film.outputs.0.type", "RGB_IMAGEPIPELINE"))
    config_props.Set(pyluxcore.Property("film.outputs.0.filename", str(output_path)))

    # Imagepipeline: tonemapping + gamma
    config_props.Set(pyluxcore.Property("film.imagepipeline.0.type", "TONEMAP_AUTOLINEAR"))
    config_props.Set(pyluxcore.Property("film.imagepipeline.1.type", "GAMMA_CORRECTION"))
    config_props.Set(pyluxcore.Property("film.imagepipeline.1.value", 2.2))

    # Halt conditions
    config_props.Set(pyluxcore.Property("batch.halttime", halt_time))
    config_props.Set(pyluxcore.Property("batch.haltspp", halt_samples))

    # Path depth (deep for recursive glass + volumetrics)
    config_props.Set(pyluxcore.Property("path.pathdepth.total", 32))
    config_props.Set(pyluxcore.Property("path.pathdepth.diffuse", 8))
    config_props.Set(pyluxcore.Property("path.pathdepth.glossy", 16))
    config_props.Set(pyluxcore.Property("path.pathdepth.specular", 32))

    # 4. Create session and render
    try:
        import time

        config = pyluxcore.RenderConfig(config_props, scene)
        session = pyluxcore.RenderSession(config)
        session.Start()

        logger.info(f"  Rendering ({halt_time}s / {halt_samples}spp)...")

        # Poll until done or timeout (halt conditions + hard timeout safety)
        hard_timeout = halt_time + 10  # extra buffer
        start_time = time.monotonic()
        while not session.HasDone():
            elapsed = time.monotonic() - start_time
            if elapsed > hard_timeout:
                logger.warning(
                    f"  Hard timeout at {elapsed:.0f}s, stopping render"
                )
                break
            time.sleep(1.0)
            session.UpdateStats()

        session.Stop()

        # Save film — execute imagepipeline (index 0) and save configured outputs
        film = session.GetFilm()
        film.ExecuteImagePipeline(0)
        film.SaveOutputs()

        elapsed = time.monotonic() - start_time
        file_size = output_path.stat().st_size
        logger.info(
            f"  Done in {elapsed:.1f}s: {output_path} ({file_size / 1024:.1f} KB)"
        )
        return output_path

    except Exception as e:
        raise RuntimeError(
            f"LuxCore render failed for card {viz_data.card_id}: {e}\n"
            "  #VIZ.00000008.LUXCOREFAIL\n"
            "  Check: pyluxcore installation, available memory"
        ) from e


def _add_materials(props: Any, data: dict) -> None:
    """Define LuxCore materials tuned for the concept-art aesthetic.

    Target: delicate translucent glass spirals, nearly invisible except at
    edges where refraction catches light. Cool blue-white palette, minimal
    warm core glow. Concept reference: gaius-viz-concept-2026-02-22a.png
    """
    curvature = data.get("curvature", 0.5)
    boundary = data.get("boundary", 0.5)

    color = _curvature_color(curvature)

    # -- Petal Glass: very clear glass, minimal emission --
    # Concept shows nearly-invisible glass with edge refraction
    props.Set(_prop("scene.materials.petal_glass.type", "glass"))
    props.Set(_prop("scene.materials.petal_glass.kr", list(color)))
    props.Set(_prop("scene.materials.petal_glass.kt", list(color)))
    props.Set(_prop("scene.materials.petal_glass.interiorior", 1.45))
    props.Set(_prop("scene.materials.petal_glass.exteriorior", 1.0))

    # Very subtle edge emission -- concept has barely-there glow
    emission_strength = 0.003 + boundary * 0.005
    props.Set(_prop("scene.materials.petal_glass.emission", [
        0.7 * emission_strength,
        0.85 * emission_strength,
        1.0 * emission_strength,
    ]))

    # Interior volume: very subtle cool absorption (not amber)
    petal_density = 0.3 + boundary * 0.5
    props.Set(_prop("scene.volumes.petal_vol.type", "homogeneous"))
    props.Set(_prop("scene.volumes.petal_vol.absorption", [
        0.08 * petal_density,  # slight red absorption -> blue tint
        0.03 * petal_density,
        0.01 * petal_density,
    ]))
    props.Set(_prop("scene.volumes.petal_vol.scattering", [0.0, 0.0, 0.0]))
    props.Set(_prop("scene.materials.petal_glass.volume.interior", "petal_vol"))

    # -- Shell Glass: clear glass, cool blue interior --
    props.Set(_prop("scene.materials.shell_glass.type", "glass"))
    props.Set(_prop("scene.materials.shell_glass.kr", list(color)))
    props.Set(_prop("scene.materials.shell_glass.kt", list(color)))
    props.Set(_prop("scene.materials.shell_glass.interiorior", 1.5))
    props.Set(_prop("scene.materials.shell_glass.exteriorior", 1.0))

    shell_emission = 0.002 + boundary * 0.003
    props.Set(_prop("scene.materials.shell_glass.emission", [
        0.7 * shell_emission,
        0.85 * shell_emission,
        1.0 * shell_emission,
    ]))

    shell_density = 1.0 + boundary * 1.5
    props.Set(_prop("scene.volumes.shell_vol.type", "homogeneous"))
    props.Set(_prop("scene.volumes.shell_vol.absorption", [
        0.12 * shell_density,
        0.06 * shell_density,
        0.0 * shell_density,
    ]))
    props.Set(_prop("scene.volumes.shell_vol.scattering", [0.0, 0.0, 0.0]))
    props.Set(_prop("scene.materials.shell_glass.volume.interior", "shell_vol"))

    # -- Plasma Core: subtle warm point, not overwhelming --
    # Concept shows a small warm center deep inside glass layers
    plasma_r = 1.0
    plasma_g = 0.7 + curvature * 0.1
    plasma_b = 0.4 + curvature * 0.15
    plasma_strength = 1.0 + boundary * 1.5
    props.Set(_prop("scene.materials.plasma_core.type", "matte"))
    props.Set(_prop("scene.materials.plasma_core.kd", [0.0, 0.0, 0.0]))
    props.Set(_prop("scene.materials.plasma_core.emission", [
        plasma_r * plasma_strength,
        plasma_g * plasma_strength,
        plasma_b * plasma_strength,
    ]))

    # -- Plasma Glow: very subtle halo --
    glow_strength = 0.3 + boundary * 0.5
    props.Set(_prop("scene.materials.plasma_glow.type", "matte"))
    props.Set(_prop("scene.materials.plasma_glow.kd", [0.0, 0.0, 0.0]))
    props.Set(_prop("scene.materials.plasma_glow.emission", [
        0.8 * glow_strength,
        0.7 * glow_strength,
        0.5 * glow_strength,
    ]))

    # -- Reflective Floor: very dark, almost invisible --
    props.Set(_prop("scene.materials.floor_mat.type", "glossy2"))
    props.Set(_prop("scene.materials.floor_mat.kd", [0.003, 0.003, 0.005]))
    props.Set(_prop("scene.materials.floor_mat.ks", [0.4, 0.4, 0.45]))
    props.Set(_prop("scene.materials.floor_mat.uroughness", 0.15))
    props.Set(_prop("scene.materials.floor_mat.vroughness", 0.15))


def _add_lights(props: Any, data: dict) -> None:
    """Add lights positioned by gradient_direction.

    LuxCore light types: point, spot, distant, projection, laser,
    constantinfinite, infinite, sky2, sun, sharpdistant.
    Area lights in LuxCore are mesh objects with emissive materials --
    we use the emissive mesh quads approach for soft shadows.
    """
    import pyluxcore

    grad_x, grad_y = data.get("gradient_direction", (0.0, 1.0))
    curvature = data.get("curvature", 0.5)
    boundary = data.get("boundary", 0.5)

    # Concept-art lighting: subtle backlight that catches glass edges,
    # cool key light, very dark environment. The glass structures should
    # be illuminated primarily by refraction/edge-catching, not direct light.

    # Key light: cool white, positioned by gradient, moderate gain
    key_x = 1.0 * grad_x + 0.6
    key_y = 1.0 * grad_y + 0.6
    key_gain = 2.0 + curvature * 1.0
    props.Set(pyluxcore.Property("scene.lights.key_light.type", "point"))
    props.Set(pyluxcore.Property("scene.lights.key_light.color", [0.9, 0.93, 1.0]))
    props.Set(pyluxcore.Property("scene.lights.key_light.gain", [key_gain, key_gain, key_gain]))
    props.Set(pyluxcore.Property("scene.lights.key_light.position", [key_x, key_y, 1.0]))

    # Fill light: cool blue, subtle
    fill_x = -0.8 * grad_x - 0.4
    fill_y = -0.8 * grad_y - 0.4
    fill_gain = 1.0 + (1 - curvature) * 0.8
    props.Set(pyluxcore.Property("scene.lights.fill_light.type", "point"))
    props.Set(pyluxcore.Property("scene.lights.fill_light.color", [0.5, 0.6, 1.0]))
    props.Set(pyluxcore.Property("scene.lights.fill_light.gain", [fill_gain, fill_gain, fill_gain]))
    props.Set(pyluxcore.Property("scene.lights.fill_light.position", [fill_x, fill_y, 0.5]))

    # Backlight: strongest light, from behind/below — catches glass edges
    # This is the primary light source in the concept art
    back_gain = 4.0 + curvature * 2.0
    props.Set(pyluxcore.Property("scene.lights.back_light.type", "point"))
    props.Set(pyluxcore.Property("scene.lights.back_light.color", [0.85, 0.9, 1.0]))
    props.Set(pyluxcore.Property("scene.lights.back_light.gain", [back_gain, back_gain, back_gain]))
    props.Set(pyluxcore.Property("scene.lights.back_light.position", [0.0, -1.0, -0.2]))

    # Rim light: subtle cool edge definition from opposite side
    props.Set(pyluxcore.Property("scene.lights.rim_light.type", "point"))
    props.Set(pyluxcore.Property("scene.lights.rim_light.color", [0.85, 0.9, 1.0]))
    props.Set(pyluxcore.Property("scene.lights.rim_light.gain", [1.5, 1.5, 1.5]))
    props.Set(pyluxcore.Property("scene.lights.rim_light.position", [-0.8, 0.5, 0.3]))

    # Inner point light: very subtle warm center
    inner_gain = 0.5 + boundary * 0.8
    props.Set(pyluxcore.Property("scene.lights.inner_light.type", "point"))
    props.Set(pyluxcore.Property("scene.lights.inner_light.color", [1.0, 0.85, 0.65]))
    props.Set(pyluxcore.Property("scene.lights.inner_light.gain", [inner_gain, inner_gain, inner_gain]))
    props.Set(pyluxcore.Property("scene.lights.inner_light.position", [0.0, 0.0, 0.0]))

    # Environment light: near-black with cool tint
    props.Set(pyluxcore.Property("scene.lights.env_light.type", "constantinfinite"))
    props.Set(pyluxcore.Property("scene.lights.env_light.color", [0.003, 0.004, 0.01]))
    props.Set(pyluxcore.Property("scene.lights.env_light.gain", [0.2, 0.2, 0.2]))


def _add_camera(props: Any, width: int, height: int) -> None:
    """Set up camera close to the glass structures.

    Concept art shows glass filling the entire frame — almost macro
    photography of the recursive structures. Camera very close, slightly
    above, looking slightly down into the glass nest.
    """
    import pyluxcore

    # Very close — almost inside the outer petals
    props.Set(pyluxcore.Property("scene.camera.type", "perspective"))
    props.Set(pyluxcore.Property("scene.camera.lookat.orig", [0.55, -0.55, 0.35]))
    props.Set(pyluxcore.Property("scene.camera.lookat.target", [0.0, 0.0, -0.02]))
    props.Set(pyluxcore.Property("scene.camera.up", [0.0, 0.0, 1.0]))

    # Moderate FOV — close camera + moderate FOV = structures fill frame
    aspect = width / height
    base_fov = 55.0
    if aspect > 1:
        fov = math.degrees(2 * math.atan(math.tan(math.radians(base_fov / 2)) * aspect))
    else:
        fov = base_fov
    props.Set(pyluxcore.Property("scene.camera.fieldofview", fov))
    props.Set(pyluxcore.Property("scene.camera.cliphither", 0.005))
    props.Set(pyluxcore.Property("scene.camera.clipyon", 50.0))


def _add_shape(
    props: Any,
    scene: Any,
    shape_type: str,
    xf: dict,
    idx: int,
    data: dict,
) -> None:
    """Generate mesh for a grammar shape and add as LuxCore inlinedmesh."""
    curvature = data.get("curvature", 0.5)
    complexity = data.get("complexity", 0.5)
    boundary = data.get("boundary", 0.5)
    s = xf.get("scale", 1.0)

    if shape_type == CORE:
        # Plasma core sphere
        core_radius = 0.08 + boundary * 0.06
        verts, faces = make_ico_sphere(core_radius, subdivisions=3)
        verts = apply_transform(verts, xf)
        normals = compute_normals(verts, faces)
        _define_mesh(props, scene, f"core_{idx}", verts, faces, normals, "plasma_core")

        # Glow halo sphere (larger)
        glow_radius = 0.35 + boundary * 0.12
        gv, gf = make_ico_sphere(glow_radius, subdivisions=3)
        gv = apply_transform(gv, xf)
        gn = compute_normals(gv, gf)
        _define_mesh(props, scene, f"glow_{idx}", gv, gf, gn, "plasma_glow")

    elif shape_type == PETAL:
        radius = 0.6 + s * 0.5
        dome = 0.12 + curvature * 0.18 + (1 - s) * 0.08
        twist = xf.get("rz", 0) * 0.3 + curvature * 0.2
        segs = 48 + int(complexity * 16)

        verts, faces = make_petal_disk(radius, segs, dome, twist)
        verts = apply_transform(verts, xf)
        normals = compute_normals(verts, faces)
        _define_mesh(props, scene, f"petal_{idx}", verts, faces, normals, "petal_glass")

    elif shape_type == SHELL:
        shell_radius = 0.25 + s * 0.2
        subdivs = min(4 + int(complexity * 2), 6)
        verts, faces = make_ico_sphere(shell_radius, subdivisions=subdivs)
        verts = apply_transform(verts, xf)
        normals = compute_normals(verts, faces)
        _define_mesh(props, scene, f"shell_{idx}", verts, faces, normals, "shell_glass")

    elif shape_type == TORUS:
        major_r = 0.4 * s + 0.1
        minor_r = 0.01 + complexity * 0.012
        verts, faces = make_torus(major_r, minor_r, 96, 12)
        verts = apply_transform(verts, xf)
        normals = compute_normals(verts, faces)
        _define_mesh(props, scene, f"torus_{idx}", verts, faces, normals, "petal_glass")

    elif shape_type == VOID:
        void_radius = 0.1 * s + complexity * 0.08 * s
        verts, faces = make_ico_sphere(void_radius, subdivisions=3)
        # Reverse face winding for void (inverted normals)
        faces = faces[:, ::-1]
        verts = apply_transform(verts, xf)
        normals = compute_normals(verts, faces)
        _define_mesh(props, scene, f"void_{idx}", verts, faces, normals, "shell_glass")

    elif shape_type == FILAMENT:
        fil_radius = 0.003 + s * 0.005
        fil_depth = max(0.05, s * 0.5)
        verts, faces = make_cylinder(fil_radius, fil_depth, 12)
        verts = apply_transform(verts, xf)
        normals = compute_normals(verts, faces)
        _define_mesh(props, scene, f"filament_{idx}", verts, faces, normals, "petal_glass")


def _add_floor(props: Any, scene: Any) -> None:
    """Add dark reflective floor plane, pushed far down."""
    # Floor much lower — barely visible, just catches subtle reflections
    verts = np.array([
        [-15, -15, -1.5],
        [15, -15, -1.5],
        [15, 15, -1.5],
        [-15, 15, -1.5],
    ], dtype=np.float32)
    faces = np.array([
        [0, 1, 2],
        [0, 2, 3],
    ], dtype=np.int32)
    normals = np.array([
        [0, 0, 1],
        [0, 0, 1],
        [0, 0, 1],
        [0, 0, 1],
    ], dtype=np.float32)
    _define_mesh(props, scene, "floor", verts, faces, normals, "floor_mat")


def _define_mesh(
    props: Any,
    scene: Any,
    name: str,
    verts: np.ndarray,
    faces: np.ndarray,
    normals: np.ndarray,
    material: str,
) -> None:
    """Register an inlinedmesh shape + object in the LuxCore scene."""
    import pyluxcore

    # Flatten arrays to lists for pyluxcore properties
    v_flat = verts.flatten().tolist()
    f_flat = faces.flatten().tolist()
    n_flat = normals.flatten().tolist()

    # Define shape
    props.Set(pyluxcore.Property(f"scene.shapes.{name}.type", "inlinedmesh"))
    props.Set(pyluxcore.Property(f"scene.shapes.{name}.vertices", v_flat))
    props.Set(pyluxcore.Property(f"scene.shapes.{name}.faces", f_flat))
    props.Set(pyluxcore.Property(f"scene.shapes.{name}.normals", n_flat))

    # Define object referencing shape + material
    props.Set(pyluxcore.Property(f"scene.objects.{name}.shape", name))
    props.Set(pyluxcore.Property(f"scene.objects.{name}.material", material))


def _prop(key: str, value: Any) -> Any:
    """Helper to create a pyluxcore Property."""
    import pyluxcore

    if isinstance(value, list):
        return pyluxcore.Property(key, value)
    return pyluxcore.Property(key, value)
