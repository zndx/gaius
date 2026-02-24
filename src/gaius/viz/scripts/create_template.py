"""Generate the recursive_glass.blend template for card visualization.

Runs once via Blender to create a .blend file containing:
  - Geometry Nodes tree (from geonodes.py)
  - All materials (petal, shell, plasma, floor) with Phase 1 improvements
  - Empty mesh with GN modifier + material slots
  - Lighting, camera, world, render, and compositor settings

Usage:
    blender --background --python create_template.py -- \
        --output src/gaius/viz/templates/recursive_glass.blend
"""

import argparse
import math
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """Parse arguments after Blender's -- separator."""
    try:
        sep_idx = sys.argv.index("--")
        script_args = sys.argv[sep_idx + 1:]
    except ValueError:
        script_args = []

    parser = argparse.ArgumentParser(description="Generate card viz template")
    parser.add_argument(
        "--output",
        required=True,
        help="Output .blend file path",
    )
    return parser.parse_args(script_args)


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
    for block in bpy.data.node_groups:
        if block.users == 0:
            bpy.data.node_groups.remove(block)


def _curvature_color(curvature: float) -> tuple:
    """Pale warm white -> visible soft blue driven by curvature."""
    r = 0.85 - curvature * 0.42
    g = 0.88 - curvature * 0.12
    b = 0.92 + curvature * 0.08
    return (r, g, b, 1.0)


def create_petal_material(curvature: float = 0.5, boundary: float = 0.5):
    """Principled glass with Light Path mixing + Volume Absorption."""
    import bpy

    mat = bpy.data.materials.new(name="PetalGlass")
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
    principled.inputs["Transmission Weight"].default_value = 1.0
    principled.inputs["Coat Weight"].default_value = 0.85
    principled.inputs["Coat Roughness"].default_value = 0.08
    principled.inputs["Coat IOR"].default_value = 1.6
    principled.inputs["Coat Tint"].default_value = color
    principled.inputs["Emission Color"].default_value = (1.0, 0.75, 0.4, 1.0)
    principled.inputs["Emission Strength"].default_value = 0.015 + boundary * 0.03

    # Light Path mixing: camera sees full glass, secondary rays see transparent
    light_path = nodes.new("ShaderNodeLightPath")
    light_path.location = (-200, 300)

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (0, 300)

    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (200, 100)

    links.new(light_path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(principled.outputs["BSDF"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])

    # Volume Absorption: warm amber interior
    vol_absorb = nodes.new("ShaderNodeVolumeAbsorption")
    vol_absorb.location = (200, -200)
    vol_absorb.inputs["Color"].default_value = (0.85, 0.65, 0.4, 1.0)
    vol_absorb.inputs["Density"].default_value = 2.0 + boundary * 3.0
    links.new(vol_absorb.outputs["Volume"], output.inputs["Volume"])

    return mat


def create_shell_material(curvature: float = 0.5, boundary: float = 0.5):
    """Crystal-clear glass shell with Volume Absorption."""
    import bpy

    mat = bpy.data.materials.new(name="ShellGlass")
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

    emission = nodes.new("ShaderNodeEmission")
    emission.location = (200, -100)
    emission.inputs["Color"].default_value = (1.0, 0.7, 0.3, 1.0)
    emission.inputs["Strength"].default_value = 0.015 + boundary * 0.04

    add = nodes.new("ShaderNodeAddShader")
    add.location = (400, 0)
    links.new(glass.outputs["BSDF"], add.inputs[0])
    links.new(emission.outputs["Emission"], add.inputs[1])
    links.new(add.outputs["Shader"], output.inputs["Surface"])

    # Volume Absorption: cool blue interior
    vol_absorb = nodes.new("ShaderNodeVolumeAbsorption")
    vol_absorb.location = (400, -200)
    vol_absorb.inputs["Color"].default_value = (0.7, 0.8, 1.0, 1.0)
    vol_absorb.inputs["Density"].default_value = 3.0 + boundary * 4.0
    links.new(vol_absorb.outputs["Volume"], output.inputs["Volume"])

    return mat


def create_plasma_material(curvature: float = 0.5, boundary: float = 0.5):
    """Inner plasma core — warm amber-orange volumetric glow."""
    import bpy

    mat = bpy.data.materials.new(name="PlasmaCore")
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


def create_plasma_glow_material(boundary: float = 0.5):
    """Larger diffuse warm glow sphere around the plasma core."""
    import bpy

    mat = bpy.data.materials.new(name="PlasmaGlow")
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (200, 0)

    emission = nodes.new("ShaderNodeEmission")
    emission.location = (0, 0)
    emission.inputs["Color"].default_value = (1.0, 0.6, 0.2, 1.0)
    emission.inputs["Strength"].default_value = 12.0 + boundary * 20.0
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


def setup_lighting():
    """Dramatic lighting for translucent glass petals."""
    import bpy

    # Key light: neutral white
    bpy.ops.object.light_add(type="AREA", location=(4.5, 4.5, 3.5))
    key = bpy.context.active_object
    key.name = "KeyLight"
    key.data.energy = 1050
    key.data.color = (0.95, 0.97, 1.0)
    key.data.size = 5.0

    # Fill light: cool blue
    bpy.ops.object.light_add(type="AREA", location=(-4.0, -4.0, 2.5))
    fill = bpy.context.active_object
    fill.name = "FillLight"
    fill.data.energy = 800
    fill.data.color = (0.5, 0.65, 1.0)
    fill.data.size = 6.0

    # Backlight: warm amber
    bpy.ops.object.light_add(type="AREA", location=(0, -4.0, 0.5))
    back = bpy.context.active_object
    back.name = "BackLight"
    back.data.energy = 1200
    back.data.color = (1.0, 0.75, 0.4)
    back.data.size = 7.0

    # Rim light
    bpy.ops.object.light_add(type="AREA", location=(-3.0, 0, 1.5))
    rim = bpy.context.active_object
    rim.name = "RimLight"
    rim.data.energy = 600
    rim.data.color = (0.92, 0.95, 1.0)
    rim.data.size = 4.0

    # Under light
    bpy.ops.object.light_add(type="POINT", location=(0, 0, -0.5))
    under = bpy.context.active_object
    under.name = "UnderLight"
    under.data.energy = 60
    under.data.color = (0.9, 0.9, 1.0)

    # Inner light (illuminates glass from core)
    bpy.ops.object.light_add(type="POINT", location=(0, 0, 0))
    inner = bpy.context.active_object
    inner.name = "InnerLight"
    inner.data.energy = 450
    inner.data.color = (1.0, 0.7, 0.3)


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
    """Dark background with subtle volume scatter."""
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

    bg = nodes.new("ShaderNodeBackground")
    bg.location = (0, 100)
    bg.inputs["Color"].default_value = (0.002, 0.003, 0.008, 1.0)
    bg.inputs["Strength"].default_value = 0.3
    links.new(bg.outputs["Background"], output.inputs["Surface"])

    vol = nodes.new("ShaderNodeVolumeScatter")
    vol.location = (0, -100)
    vol.inputs["Color"].default_value = (0.5, 0.55, 0.7, 1.0)
    vol.inputs["Density"].default_value = 0.004
    vol.inputs["Anisotropy"].default_value = 0.3
    links.new(vol.outputs["Volume"], output.inputs["Volume"])


def setup_render():
    """Configure Cycles render settings."""
    import bpy

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"

    scene.cycles.samples = 256
    scene.cycles.use_denoising = True

    scene.render.resolution_x = 1400
    scene.render.resolution_y = 600
    scene.render.resolution_percentage = 100

    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.compression = 15
    scene.render.film_transparent = False

    # Adaptive sampling
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.05
    scene.cycles.adaptive_min_samples = 64
    scene.render.threads_mode = "AUTO"

    # High bounce budget
    scene.cycles.max_bounces = 64
    scene.cycles.glossy_bounces = 16
    scene.cycles.transmission_bounces = 48
    scene.cycles.transparent_max_bounces = 64
    scene.cycles.volume_bounces = 8
    scene.cycles.diffuse_bounces = 8

    scene.cycles.caustics_reflective = True
    scene.cycles.caustics_refractive = True

    # Blender 5.0: unbiased null-scattering for clean overlapping glass volumes
    scene.cycles.volume_biased = False

    # Color management: ACEScg wide-gamut for vibrant refractive highlights
    scene.view_settings.view_transform = "ACES 2.0"


def setup_compositor():
    """Two-stage compositor glare: Bloom + Fog Glow.

    Blender 5.0 API: uses scene.compositing_node_group with socket-based
    Glare node inputs.
    """
    import bpy

    scene = bpy.context.scene

    tree = bpy.data.node_groups.new("CardVizCompositor", "CompositorNodeTree")
    scene.compositing_node_group = tree

    nodes = tree.nodes
    links = tree.links

    rl = nodes.new("CompositorNodeRLayers")
    rl.location = (0, 0)

    bloom = nodes.new("CompositorNodeGlare")
    bloom.location = (300, 0)
    bloom.inputs["Type"].default_value = "Bloom"
    bloom.inputs["Quality"].default_value = "High"
    bloom.inputs["Threshold"].default_value = 0.8
    bloom.inputs["Size"].default_value = 0.7

    fog = nodes.new("CompositorNodeGlare")
    fog.location = (600, 0)
    fog.inputs["Type"].default_value = "Fog Glow"
    fog.inputs["Quality"].default_value = "High"
    fog.inputs["Threshold"].default_value = 1.2
    fog.inputs["Size"].default_value = 0.6

    tree.interface.new_socket(
        name="Image", in_out="OUTPUT", socket_type="NodeSocketColor"
    )
    group_out = nodes.new("NodeGroupOutput")
    group_out.location = (900, 0)

    links.new(rl.outputs["Image"], bloom.inputs["Image"])
    links.new(bloom.outputs["Image"], fog.inputs["Image"])
    links.new(fog.outputs["Image"], group_out.inputs["Image"])


def create_manifold_object(gn_tree, materials: list):
    """Create the main mesh object with Geometry Nodes modifier.

    Args:
        gn_tree: The GeometryNodeTree to assign
        materials: List of materials [petal, shell, plasma, plasma_glow]
    """
    import bpy

    # Create empty mesh
    mesh = bpy.data.meshes.new("ManifoldMesh")
    obj = bpy.data.objects.new("Manifold", mesh)
    bpy.context.collection.objects.link(obj)

    # Assign materials in order matching material indices in geonodes
    for mat in materials:
        obj.data.materials.append(mat)

    # Add Geometry Nodes modifier
    mod = obj.modifiers.new(name="ManifoldGeoNodes", type="NODES")
    mod.node_group = gn_tree

    return obj


def create_floor():
    """Dark reflective floor plane."""
    import bpy

    floor_mat = create_floor_material()
    bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, -0.72))
    floor = bpy.context.active_object
    floor.name = "ReflectiveFloor"
    floor.data.materials.append(floor_mat)
    return floor


def main():
    """Generate the recursive_glass.blend template."""
    import bpy

    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("Creating recursive glass template...")

    # 1. Clear scene
    clear_scene()

    # 2. Build Geometry Nodes tree
    # Import geonodes from same directory
    scripts_dir = str(Path(__file__).parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from geonodes import build_manifold_geonodes

    gn_tree = build_manifold_geonodes()
    print(f"  Built GN tree: {gn_tree.name} ({len(gn_tree.nodes)} nodes)")

    # 3. Create materials (with default curvature/boundary — overridden at render time)
    petal_mat = create_petal_material()
    shell_mat = create_shell_material()
    plasma_mat = create_plasma_material()
    glow_mat = create_plasma_glow_material()

    # 4. Create manifold object with GN modifier
    # Material order: [0]=petal, [1]=shell, [2]=plasma, [3]=glow
    manifold = create_manifold_object(
        gn_tree, [petal_mat, shell_mat, plasma_mat, glow_mat]
    )
    print(f"  Created manifold object with {len(manifold.data.materials)} materials")

    # 5. Create floor
    create_floor()

    # 6. Setup scene
    setup_world()
    setup_lighting()
    setup_camera()
    setup_render()
    setup_compositor()

    # 7. Save as .blend
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
    print(f"  Saved template: {output_path}")
    print(f"  Node groups: {[ng.name for ng in bpy.data.node_groups]}")


if __name__ == "__main__":
    main()
