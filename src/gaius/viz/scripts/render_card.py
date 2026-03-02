"""Blender-side render script for card visualizations.

Runs inside Blender's Python interpreter (bpy). Creates a procedural
glass-plasma scene parameterized by CardVizData JSON, then renders to PNG.

Aesthetic: translucent glass petals with inner plasma glow — flowing curved
surfaces showing soft translucency face-on and crisp glass refraction at
edges, warm amber core bleeding through cool blue-white structures, layered
petal arrangement with volume atmosphere and dark reflective floor.

Topology features drive geometry:
  persistence → nesting depth (recursive thin shells)
  b1          → flowing ribbon loops
  b2          → enclosed void chambers
  curvature   → color (warm white ↔ ice blue), petal curvature
  complexity  → subdivision detail, organic displacement
  boundary    → inner plasma glow intensity

Usage (from command line):
    blender --background --python render_card.py -- --input data.json --output out.png
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """Parse arguments after Blender's -- separator."""
    try:
        sep_idx = sys.argv.index("--")
        script_args = sys.argv[sep_idx + 1:]
    except ValueError:
        script_args = []

    parser = argparse.ArgumentParser(description="Render card visualization")
    parser.add_argument("--input", required=True, help="Input JSON path")
    parser.add_argument("--output", required=True, help="Output PNG path")
    parser.add_argument("--samples", type=int, default=256, help="Render samples")
    parser.add_argument("--width", type=int, default=1400, help="Output width in pixels")
    parser.add_argument("--height", type=int, default=300, help="Output height in pixels")
    return parser.parse_args(script_args)


def setup_gpu():
    """Enable GPU rendering if available.

    Tries compute backends in order: OptiX (fastest for RTX), CUDA, HIP, Metal.
    Verifies that devices actually match the requested backend type — Blender
    may list CUDA devices even when OptiX initialization failed.
    """
    import bpy

    prefs = bpy.context.preferences
    cycles_prefs = prefs.addons["cycles"].preferences

    for compute_type in ("OPTIX", "CUDA", "HIP", "METAL"):
        try:
            cycles_prefs.compute_device_type = compute_type
            cycles_prefs.get_devices()
            # Only count devices whose type matches the requested backend
            gpu_devices = [d for d in cycles_prefs.devices if d.type == compute_type]
            if gpu_devices:
                for device in gpu_devices:
                    device.use = True
                # Disable CPU device for GPU-only rendering
                for device in cycles_prefs.devices:
                    if device.type == "CPU":
                        device.use = False
                names = [d.name for d in gpu_devices]
                print(f"GPU: Using {compute_type} with {len(gpu_devices)} device(s): {names}")
                return True
        except Exception:
            continue

    print("GPU: No OptiX/CUDA/HIP/Metal available, using CPU")
    return False


def clear_scene():
    """Remove all default objects from the scene."""
    import bpy

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def _curvature_color(curvature: float) -> tuple:
    """Pale warm white ↔ visible soft blue driven by curvature.

    More saturated than typical glass base colors — the Principled BSDF
    with full transmission dilutes color heavily, so we start stronger
    to get a noticeable blue tint in the final render.
    """
    r = 0.85 - curvature * 0.42     # 0.85 → 0.43
    g = 0.88 - curvature * 0.12     # 0.88 → 0.76
    b = 0.92 + curvature * 0.08     # 0.92 → 1.00
    return (r, g, b, 1.0)



def create_petal_material(name: str, curvature: float, boundary: float):
    """Principled glass veil — the signature flowing-petal look.

    Uses Principled BSDF with full transmission for a glass-like surface
    that's still visible (specular reflections, refraction) while letting
    light pass through.  Slight roughness creates the soft luminous quality
    from the concept art.  Warm emission adds inner glow.
    """
    import bpy

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (400, 0)

    color = _curvature_color(curvature)

    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (0, 0)
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Roughness"].default_value = 0.12
    principled.inputs["IOR"].default_value = 1.5
    principled.inputs["Metallic"].default_value = 0.0
    principled.inputs["Alpha"].default_value = 1.0

    # Glass-like transmission — lets light through
    principled.inputs["Transmission Weight"].default_value = 1.0

    # Subtle coat — thin tinted sheen, minimal opacity
    principled.inputs["Coat Weight"].default_value = 0.15
    principled.inputs["Coat Roughness"].default_value = 0.04
    principled.inputs["Coat IOR"].default_value = 1.5
    principled.inputs["Coat Tint"].default_value = color

    # Subtle warm emission — petal surfaces glow softly
    principled.inputs["Emission Color"].default_value = (1.0, 0.75, 0.4, 1.0)
    principled.inputs["Emission Strength"].default_value = 0.015 + boundary * 0.03

    # --- Light Path mixing: camera sees full glass, secondary rays see
    # transparent to prevent multiplicative darkening from overlapping petals ---
    light_path = nodes.new("ShaderNodeLightPath")
    light_path.location = (-200, 300)

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (0, 300)

    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (200, 100)

    links.new(light_path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])  # non-camera → transparent
    links.new(principled.outputs["BSDF"], mix.inputs[2])   # camera → full glass

    links.new(mix.outputs["Shader"], output.inputs["Surface"])

    # --- Volume Absorption: warm amber interior tint (lower density for clarity) ---
    vol_absorb = nodes.new("ShaderNodeVolumeAbsorption")
    vol_absorb.location = (200, -200)
    vol_absorb.inputs["Color"].default_value = (0.85, 0.65, 0.4, 1.0)
    vol_absorb.inputs["Density"].default_value = 0.8 + boundary * 1.5

    links.new(vol_absorb.outputs["Volume"], output.inputs["Volume"])

    return mat


def create_shell_material(name: str, curvature: float, boundary: float):
    """Crystal-clear glass shell for inner nested structures.

    Pure Glass BSDF with very pale curvature-driven color and slight
    roughness for soft refraction.  Thin solidify walls on the mesh create
    natural bubble-like translucency.
    """
    import bpy

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (600, 0)

    glass = nodes.new("ShaderNodeBsdfGlass")
    glass.location = (200, 100)
    glass.inputs["Color"].default_value = _curvature_color(curvature)
    glass.inputs["IOR"].default_value = 1.5
    glass.inputs["Roughness"].default_value = 0.02

    # Subtle warm emission
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (200, -100)
    emission.inputs["Color"].default_value = (1.0, 0.7, 0.3, 1.0)
    emission.inputs["Strength"].default_value = 0.015 + boundary * 0.04

    add = nodes.new("ShaderNodeAddShader")
    add.location = (400, 0)
    links.new(glass.outputs["BSDF"], add.inputs[0])
    links.new(emission.outputs["Emission"], add.inputs[1])
    links.new(add.outputs["Shader"], output.inputs["Surface"])

    # --- Volume Absorption: cool blue interior depth for shell glass ---
    vol_absorb = nodes.new("ShaderNodeVolumeAbsorption")
    vol_absorb.location = (400, -200)
    vol_absorb.inputs["Color"].default_value = (0.7, 0.8, 1.0, 1.0)
    vol_absorb.inputs["Density"].default_value = 3.0 + boundary * 4.0

    links.new(vol_absorb.outputs["Volume"], output.inputs["Volume"])

    return mat


def create_plasma_material(name: str, curvature: float, boundary: float):
    """Inner plasma core — warm amber-orange volumetric glow."""
    import bpy

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (400, 0)

    emission = nodes.new("ShaderNodeEmission")
    emission.location = (0, 0)
    r = 1.0
    g = 0.55 + curvature * 0.15
    b = 0.1 + curvature * 0.1
    emission.inputs["Color"].default_value = (r, g, b, 1.0)
    emission.inputs["Strength"].default_value = 40.0 + boundary * 60.0

    links.new(emission.outputs["Emission"], output.inputs["Surface"])

    return mat


def create_floor_material():
    """Dark reflective floor — glossy for mirror effect."""
    import bpy

    mat = bpy.data.materials.new(name="ReflectiveFloor")
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (400, 0)

    glossy = nodes.new("ShaderNodeBsdfGlossy")
    glossy.location = (0, 0)
    glossy.inputs["Color"].default_value = (0.01, 0.01, 0.015, 1.0)
    glossy.inputs["Roughness"].default_value = 0.08

    links.new(glossy.outputs["BSDF"], output.inputs["Surface"])

    return mat


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def _create_petal(name: str, radius: float, dome_factor: float,
                  location: tuple, rotation: tuple, scale: tuple,
                  material, complexity: float, twist_angle: float = 0.0):
    """Create a single flowing petal shape.

    Built from a filled circle → Cast to sphere (dome) → twist → solidify.
    This produces the smooth, curved veil surfaces from the concept art.
    """
    import bpy

    # Start with a filled circle (triangle fan for clean subsurf behavior)
    vert_count = 48 + int(complexity * 16)
    bpy.ops.mesh.primitive_circle_add(
        vertices=vert_count, radius=radius,
        fill_type='TRIFAN', location=location, rotation=rotation,
    )
    petal = bpy.context.active_object
    petal.name = name
    petal.scale = scale
    petal.data.materials.append(material)

    # Cast to sphere: flat circle → dome shape
    cast = petal.modifiers.new("DomeCast", "CAST")
    cast.cast_type = 'SPHERE'
    cast.factor = dome_factor

    # Twist for flowing organic curve
    if abs(twist_angle) > 0.01:
        twist = petal.modifiers.new("Twist", "SIMPLE_DEFORM")
        twist.deform_method = 'TWIST'
        twist.angle = twist_angle

    # Subdivision for smoothness (before solidify for clean edges)
    sub = petal.modifiers.new("Subsurf", "SUBSURF")
    sub.levels = 2
    sub.render_levels = 3

    # Solidify: thick enough for glass color to be visible
    solidify = petal.modifiers.new("Solidify", "SOLIDIFY")
    solidify.thickness = 0.015 + complexity * 0.01
    solidify.offset = -1

    bpy.ops.object.shade_smooth()
    return petal


# ---------------------------------------------------------------------------
# Grammar engine — imported from gaius.viz.grammar (shared with LuxCore path)
# ---------------------------------------------------------------------------
# When running inside Blender's Python, the gaius package may not be on
# sys.path. We add the project src/ directory to enable the import.

try:
    from gaius.viz.grammar import (
        CORE as _CORE,
        FILAMENT as _FILAMENT,
        PETAL as _PETAL,
        SHELL as _SHELL,
        TORUS as _TORUS,
        VOID as _VOID,
        expand_grammar,
    )
except ImportError:
    import os as _os
    _src_dir = _os.path.abspath(
        _os.path.join(_os.path.dirname(__file__), "..", "..", "..")
    )
    if _src_dir not in sys.path:
        sys.path.insert(0, _src_dir)
    from gaius.viz.grammar import (
        CORE as _CORE,
        FILAMENT as _FILAMENT,
        PETAL as _PETAL,
        SHELL as _SHELL,
        TORUS as _TORUS,
        VOID as _VOID,
        expand_grammar,
    )


def realize_shapes(shapes, data):
    """Create Blender objects from expanded grammar shapes.

    Maps each (shape_type, transform) to actual Blender geometry,
    applying materials and modifiers as before.
    """
    import bpy
    import bmesh

    curvature = data.get("curvature", 0.5)
    persistence = data.get("persistence", 0.5)
    complexity = data.get("complexity", 0.5)
    boundary = data.get("boundary", 0.5)

    petal_mat = create_petal_material("PetalGlass", curvature, boundary)
    shell_mat = create_shell_material("ShellGlass", curvature, boundary)
    plasma_mat = create_plasma_material("PlasmaCore", curvature, boundary)

    objects = []
    counters = {"petal": 0, "shell": 0, "torus": 0, "void": 0, "filament": 0}

    for shape_type, xf in shapes:

        if shape_type == _CORE:
            # Plasma core + glow sphere + inner point light
            core_radius = 0.08 + boundary * 0.06
            bpy.ops.mesh.primitive_ico_sphere_add(
                subdivisions=3, radius=core_radius,
                location=(xf["x"], xf["y"], xf["z"]),
            )
            core = bpy.context.active_object
            core.name = "PlasmaCore"
            core.data.materials.append(plasma_mat)
            bpy.ops.object.shade_smooth()
            objects.append(core)

            # Glow halo
            glow_mat = bpy.data.materials.new(name="PlasmaGlow")
            gn = glow_mat.node_tree.nodes
            gl = glow_mat.node_tree.links
            gn.clear()
            glow_out = gn.new("ShaderNodeOutputMaterial")
            glow_out.location = (200, 0)
            glow_emit = gn.new("ShaderNodeEmission")
            glow_emit.location = (0, 0)
            glow_emit.inputs["Color"].default_value = (1.0, 0.6, 0.2, 1.0)
            glow_emit.inputs["Strength"].default_value = 12.0 + boundary * 20.0
            gl.new(glow_emit.outputs["Emission"], glow_out.inputs["Surface"])

            glow_radius = 0.35 + boundary * 0.12
            bpy.ops.mesh.primitive_ico_sphere_add(
                subdivisions=3, radius=glow_radius,
                location=(xf["x"], xf["y"], xf["z"]),
            )
            glow = bpy.context.active_object
            glow.name = "PlasmaGlow"
            glow.data.materials.append(glow_mat)
            bpy.ops.object.shade_smooth()
            objects.append(glow)

            # Inner point light
            bpy.ops.object.light_add(
                type="POINT", location=(xf["x"], xf["y"], xf["z"]))
            inner_light = bpy.context.active_object
            inner_light.name = "InnerLight"
            inner_light.data.energy = 300 + boundary * 300
            inner_light.data.color = (1.0, 0.7, 0.3)

        elif shape_type == _PETAL:
            idx = counters["petal"]
            counters["petal"] += 1
            s = xf["scale"]

            # Petal radius: 0.6-1.1 range (matches original 0.8-1.35)
            radius = 0.6 + s * 0.5
            # Lower dome → flatter veil shapes that show arrangement variety
            dome = 0.12 + curvature * 0.18 + (1 - s) * 0.08
            twist = xf["rz"] * 0.3 + curvature * 0.2

            # Non-uniform scale: elongated petals like original
            sx = s * (1.0 + 0.3 * math.sin(xf["rx"] * 3))
            sy = s * (1.0 + 0.2 * math.cos(xf["ry"] * 3))
            sz = s

            petal = _create_petal(
                name=f"Petal_{idx}",
                radius=radius,
                dome_factor=dome,
                location=(xf["x"], xf["y"], xf["z"]),
                rotation=(xf["rx"], xf["ry"], xf["rz"]),
                scale=(sx, sy, sz),
                material=petal_mat,
                complexity=complexity,
                twist_angle=twist,
            )
            objects.append(petal)

        elif shape_type == _SHELL:
            idx = counters["shell"]
            counters["shell"] += 1
            s = xf["scale"]

            shell_radius = 0.25 + s * 0.2
            subdivs = min(4 + int(complexity * 2), 6)
            bpy.ops.mesh.primitive_ico_sphere_add(
                subdivisions=subdivs, radius=shell_radius,
                location=(xf["x"], xf["y"], xf["z"]),
            )
            shell = bpy.context.active_object
            shell.name = f"Shell_{idx}"
            shell.data.materials.append(shell_mat)
            bpy.ops.object.shade_smooth()

            solidify = shell.modifiers.new("Solidify", "SOLIDIFY")
            solidify.thickness = 0.008 + complexity * 0.006
            solidify.offset = -1
            objects.append(shell)

        elif shape_type == _TORUS:
            idx = counters["torus"]
            counters["torus"] += 1
            s = xf["scale"]

            bpy.ops.mesh.primitive_torus_add(
                major_radius=0.4 * s + 0.1,
                minor_radius=0.01 + complexity * 0.012,
                major_segments=96,
                minor_segments=12,
                location=(xf["x"], xf["y"], xf["z"]),
                rotation=(xf["rx"], xf["ry"], xf["rz"]),
            )
            torus = bpy.context.active_object
            torus.name = f"Ribbon_{idx}"
            torus.data.materials.append(petal_mat)
            bpy.ops.object.shade_smooth()
            objects.append(torus)

        elif shape_type == _VOID:
            idx = counters["void"]
            counters["void"] += 1
            s = xf["scale"]

            bpy.ops.mesh.primitive_ico_sphere_add(
                subdivisions=3,
                radius=0.1 * s + complexity * 0.08 * s,
                location=(xf["x"], xf["y"], xf["z"]),
            )
            void_obj = bpy.context.active_object
            void_obj.name = f"Void_{idx}"

            bpy.ops.object.mode_set(mode="EDIT")
            bm = bmesh.from_edit_mesh(void_obj.data)
            bmesh.ops.reverse_faces(bm, faces=bm.faces)
            bmesh.update_edit_mesh(void_obj.data)
            bpy.ops.object.mode_set(mode="OBJECT")

            void_obj.data.materials.append(shell_mat)
            solidify = void_obj.modifiers.new("Solidify", "SOLIDIFY")
            solidify.thickness = 0.01
            solidify.offset = -1
            bpy.ops.object.shade_smooth()
            objects.append(void_obj)

        elif shape_type == _FILAMENT:
            idx = counters["filament"]
            counters["filament"] += 1
            s = xf["scale"]

            bpy.ops.mesh.primitive_cylinder_add(
                radius=0.003 + s * 0.005,
                depth=max(0.05, s * 0.5),
                location=(xf["x"], xf["y"], xf["z"]),
                rotation=(xf["rx"], xf["ry"], xf["rz"]),
            )
            filament = bpy.context.active_object
            filament.name = f"Filament_{idx}"
            filament.data.materials.append(petal_mat)
            bpy.ops.object.shade_smooth()
            objects.append(filament)

    print(f"  Realized: {counters}")
    return objects


def create_manifold_geometry(data: dict):
    """Create the procedural glass-plasma manifold via grammar expansion.

    CFDG-inspired: card topology features control rule weights,
    hash(card_id) seeds the RNG → each card is unique but reproducible.
    """
    shapes = expand_grammar(data)
    return realize_shapes(shapes, data)


def create_reflective_floor():
    """Dark reflective floor plane."""
    import bpy

    floor_mat = create_floor_material()

    bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, -0.72))
    floor = bpy.context.active_object
    floor.name = "ReflectiveFloor"
    floor.data.materials.append(floor_mat)

    return floor


# ---------------------------------------------------------------------------
# Scene setup
# ---------------------------------------------------------------------------

def setup_lighting(data: dict):
    """Dramatic lighting for translucent glass petals.

    Strong backlight is critical — it creates the luminous edge glow that
    makes translucent surfaces look ethereal.  Key light is near-neutral
    to let the glass colors show through undistorted.
    """
    import bpy

    grad_x, grad_y = data.get("gradient_direction", (0.0, 1.0))
    curvature = data.get("curvature", 0.5)

    # ALL LIGHTS NEUTRAL/COOL — warmth comes ONLY from the plasma core
    # This creates the concept's look: blue-white surfaces with warm amber
    # bleeding through from the emissive center.

    # Key light: neutral white
    key_pos = (2.5 * grad_x + 2.0, 2.5 * grad_y + 2.0, 3.5)
    bpy.ops.object.light_add(type="AREA", location=key_pos)
    key = bpy.context.active_object
    key.name = "KeyLight"
    key.data.energy = 900 + curvature * 300
    key.data.color = (0.95, 0.97, 1.0)
    key.data.size = 5.0

    # Fill light: cool blue
    fill_pos = (-2.5 * grad_x - 1.5, -2.5 * grad_y - 1.5, 2.5)
    bpy.ops.object.light_add(type="AREA", location=fill_pos)
    fill = bpy.context.active_object
    fill.name = "FillLight"
    fill.data.energy = 600 + (1 - curvature) * 400
    fill.data.color = (0.5, 0.65, 1.0)
    fill.data.size = 6.0

    # Backlight: warm amber from behind — visible through translucent petals
    # Cool key + warm back = the concept's signature warm/cool interplay
    bpy.ops.object.light_add(type="AREA", location=(0, -4.0, 0.5))
    back = bpy.context.active_object
    back.name = "BackLight"
    back.data.energy = 1200
    back.data.color = (1.0, 0.75, 0.4)  # Warm amber
    back.data.size = 7.0

    # Rim light: neutral white for edge definition
    bpy.ops.object.light_add(type="AREA", location=(-3.0, 0, 1.5))
    rim = bpy.context.active_object
    rim.name = "RimLight"
    rim.data.energy = 600
    rim.data.color = (0.92, 0.95, 1.0)
    rim.data.size = 4.0

    # Under light: neutral glow for floor reflections
    bpy.ops.object.light_add(type="POINT", location=(0, 0, -0.5))
    under = bpy.context.active_object
    under.name = "UnderLight"
    under.data.energy = 60
    under.data.color = (0.9, 0.9, 1.0)


def setup_camera():
    """Camera positioned for wide card format with dramatic angle."""
    import bpy

    bpy.ops.object.camera_add(
        location=(3.2, -3.2, 1.8),
        rotation=(math.radians(62), 0, math.radians(45)),
    )
    camera = bpy.context.active_object
    camera.name = "VizCamera"
    camera.data.lens = 36
    camera.data.clip_end = 100

    bpy.context.scene.camera = camera


def setup_world():
    """Dark background with subtle volume scatter for atmospheric depth."""
    import bpy

    world = bpy.data.worlds.get("World")
    if world is None:
        world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world

    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputWorld")
    output.location = (400, 0)

    # Very dark blue-black background
    bg = nodes.new("ShaderNodeBackground")
    bg.location = (0, 100)
    bg.inputs["Color"].default_value = (0.002, 0.003, 0.008, 1.0)
    bg.inputs["Strength"].default_value = 0.3
    links.new(bg.outputs["Background"], output.inputs["Surface"])

    # Subtle volume scatter for atmospheric depth / light bloom
    vol = nodes.new("ShaderNodeVolumeScatter")
    vol.location = (0, -100)
    vol.inputs["Color"].default_value = (0.5, 0.55, 0.7, 1.0)
    vol.inputs["Density"].default_value = 0.004
    vol.inputs["Anisotropy"].default_value = 0.3
    links.new(vol.outputs["Volume"], output.inputs["Volume"])


def setup_render(samples: int, output_path: str, width: int = 1400, height: int = 300):
    """Configure Cycles for glass-plasma rendering."""
    import bpy

    scene = bpy.context.scene

    scene.render.engine = "CYCLES"

    has_gpu = setup_gpu()
    scene.cycles.device = "GPU" if has_gpu else "CPU"

    scene.cycles.samples = samples
    scene.cycles.use_denoising = True

    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100

    scene.render.filepath = output_path
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.compression = 15

    scene.render.film_transparent = False

    # Adaptive sampling — relaxed threshold converges faster in low-noise regions
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.05
    scene.cycles.adaptive_min_samples = 64
    scene.render.threads_mode = "AUTO"

    # High bounce budget — recursive glass + volume absorption needs deep paths
    scene.cycles.max_bounces = 64
    scene.cycles.glossy_bounces = 16
    scene.cycles.transmission_bounces = 48
    scene.cycles.transparent_max_bounces = 64
    scene.cycles.volume_bounces = 8
    scene.cycles.diffuse_bounces = 8

    # Enable caustics for glass refraction patterns
    scene.cycles.caustics_reflective = True
    scene.cycles.caustics_refractive = True

    # Blender 5.0: unbiased null-scattering for clean overlapping glass volumes
    # (volume_biased=False is the 5.0 default, explicit for clarity)
    scene.cycles.volume_biased = False

    # Color management: ACEScg wide-gamut for vibrant refractive highlights
    scene.view_settings.view_transform = "ACES 2.0"


def setup_compositor():
    """Two-stage compositor glare for bloom and atmospheric fog glow.

    Blender 5.0 API: uses scene.compositing_node_group (CompositorNodeTree)
    with socket-based Glare node inputs instead of properties.

    Chain: RenderLayers → Bloom (tight halos) → FogGlow (wide haze) → Output
    """
    import bpy

    scene = bpy.context.scene

    # Blender 5.0: compositor uses a node group, not scene.node_tree
    tree = bpy.data.node_groups.new("CardVizCompositor", "CompositorNodeTree")
    scene.compositing_node_group = tree

    nodes = tree.nodes
    links = tree.links

    # Render Layers input
    rl = nodes.new("CompositorNodeRLayers")
    rl.location = (0, 0)

    # Stage 1: Bloom — tight bright halos around emissive highlights
    bloom = nodes.new("CompositorNodeGlare")
    bloom.location = (300, 0)
    bloom.inputs["Type"].default_value = "Bloom"
    bloom.inputs["Quality"].default_value = "High"
    bloom.inputs["Threshold"].default_value = 0.8
    bloom.inputs["Size"].default_value = 0.7  # Blender 5.0: float 0-1

    # Stage 2: Fog Glow — wide atmospheric haze from plasma core
    fog = nodes.new("CompositorNodeGlare")
    fog.location = (600, 0)
    fog.inputs["Type"].default_value = "Fog Glow"
    fog.inputs["Quality"].default_value = "High"
    fog.inputs["Threshold"].default_value = 1.2
    fog.inputs["Size"].default_value = 0.6

    # Output — Blender 5.0 compositor node groups use NodeGroupOutput
    # Add an Image output socket to the tree interface
    tree.interface.new_socket(
        name="Image", in_out="OUTPUT", socket_type="NodeSocketColor"
    )
    group_out = nodes.new("NodeGroupOutput")
    group_out.location = (900, 0)

    # Chain: RL → Bloom → FogGlow → Output
    links.new(rl.outputs["Image"], bloom.inputs["Image"])
    links.new(bloom.outputs["Image"], fog.inputs["Image"])
    links.new(fog.outputs["Image"], group_out.inputs["Image"])


def _has_template_scene():
    """Check if a template .blend was loaded (has ManifoldGeoNodes group)."""
    import bpy

    return "ManifoldGeoNodes" in bpy.data.node_groups


def _set_gn_inputs(data: dict):
    """Set Geometry Nodes modifier inputs from CardVizData on the Manifold object.

    Maps CardVizData fields to GN modifier socket values:
      curvature   → Curvature (float 0-1)
      persistence → Persistence (float 0-1) + NestingDepth (int 1-5)
      complexity  → Complexity (float 0-1)
      boundary    → Boundary (float 0-1)
      b1          → B1 (int, capped at 5)
      b2          → B2 (int, capped at 3)
    """
    import bpy

    obj = bpy.data.objects.get("Manifold")
    if obj is None:
        print("WARNING: No 'Manifold' object found in template, falling back to procedural")
        return False

    mod = obj.modifiers.get("ManifoldGeoNodes")
    if mod is None:
        print("WARNING: No 'ManifoldGeoNodes' modifier found, falling back to procedural")
        return False

    curvature = data.get("curvature", 0.5)
    persistence = data.get("persistence", 0.5)
    complexity = data.get("complexity", 0.5)
    boundary = data.get("boundary", 0.5)
    b1 = min(data.get("b1", 0), 5)
    b2 = min(data.get("b2", 0), 3)

    # Persistence → NestingDepth: map [0,1] to [1,5]
    nesting_depth = max(1, min(5, int(1 + persistence * 4)))

    # Set socket values via modifier items (Blender 4.x API)
    # Socket identifiers use the tree interface item identifiers
    for item in mod.node_group.interface.items_tree:
        if item.in_out != "INPUT":
            continue
        socket_id = item.identifier
        if item.name == "Curvature":
            mod[socket_id] = curvature
        elif item.name == "Persistence":
            mod[socket_id] = persistence
        elif item.name == "Complexity":
            mod[socket_id] = complexity
        elif item.name == "Boundary":
            mod[socket_id] = boundary
        elif item.name == "B1":
            mod[socket_id] = b1
        elif item.name == "B2":
            mod[socket_id] = b2
        elif item.name == "NestingDepth":
            mod[socket_id] = nesting_depth

    # Force depsgraph update
    obj.data.update()

    print(f"  GN inputs: κ={curvature:.2f} π={persistence:.2f} "
          f"nest={nesting_depth} b1={b1} b2={b2}")
    return True


def main():
    """Main entry point for Blender script.

    Two paths:
    1. Template mode: .blend loaded by renderer → set GN inputs + render settings → render
    2. Procedural mode: no template → build entire scene from scratch → render
    """
    import bpy

    args = parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)

    with open(input_path) as f:
        data = json.load(f)

    print(f"Rendering card: {data.get('card_id', 'unknown')}")
    print(f"  curvature={data.get('curvature', 0):.3f}")
    print(f"  persistence={data.get('persistence', 0):.3f}")
    print(f"  b0={data.get('b0', 0)} b1={data.get('b1', 0)} b2={data.get('b2', 0)}")
    print(f"  complexity={data.get('complexity', 0):.3f}")
    print(f"  boundary={data.get('boundary', 0):.3f}")

    if _has_template_scene():
        # Template mode: scene already loaded from .blend
        print("  Using template: ManifoldGeoNodes")
        gn_ok = _set_gn_inputs(data)
        if not gn_ok:
            # Fallback: build scene procedurally
            print("  GN input setup failed, falling back to procedural path")
            clear_scene()
            setup_world()
            create_manifold_geometry(data)
            create_reflective_floor()
            setup_lighting(data)
            setup_camera()
        # Always apply render settings (resolution/samples may differ from template defaults)
        setup_render(args.samples, args.output, args.width, args.height)
        setup_compositor()
    else:
        # Procedural mode: build scene from scratch
        print("  No template found, building scene procedurally")
        clear_scene()
        setup_world()
        create_manifold_geometry(data)
        create_reflective_floor()
        setup_lighting(data)
        setup_camera()
        setup_render(args.samples, args.output, args.width, args.height)
        setup_compositor()

    # Render (with CPU fallback if GPU fails)
    print(f"Rendering to {args.output}...")
    try:
        bpy.ops.render.render(write_still=True)
    except RuntimeError as e:
        err_msg = str(e)
        if "compilation" in err_msg.lower() or "cumodule" in err_msg.lower():
            print(f"GPU render failed ({err_msg[:80]}), retrying with CPU...")
            bpy.context.scene.cycles.device = "CPU"
            bpy.ops.render.render(write_still=True)
        else:
            raise
    print(f"Render complete: {args.output}")


if __name__ == "__main__":
    main()
