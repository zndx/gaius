"""Geometry Nodes tree builder for recursive glass manifold visualization.

Pure-function module that programmatically constructs a GeometryNodeTree
in Blender. No rendering logic — this only builds the node graph.

The tree implements topology-driven procedural geometry:
  persistence → Repeat Zone iteration count (1-5 nested shells)
  curvature   → spiral arm curvature + petal dome factor
  b1          → torus instance count
  b2          → void instance count
  complexity  → spiral resolution + subdivision detail
  boundary    → plasma core intensity (emissive strength)

Usage (inside Blender Python):
    from geonodes import build_manifold_geonodes
    tree = build_manifold_geonodes()
"""

import math


def build_manifold_geonodes():
    """Build a GeometryNodeTree for the recursive glass manifold.

    Returns:
        bpy.types.NodeTree: The constructed Geometry Nodes tree

    Interface sockets (all driven by CardVizData):
        Float: Curvature, Persistence, Complexity, Boundary
        Integer: B1, B2, NestingDepth
    """
    import bpy

    # Create new node tree
    tree = bpy.data.node_groups.new(
        name="ManifoldGeoNodes", type="GeometryNodeTree"
    )

    nodes = tree.nodes
    links = tree.links

    # -----------------------------------------------------------------------
    # Interface sockets (inputs/outputs)
    # -----------------------------------------------------------------------
    # Blender 4.x uses tree.interface for socket management
    tree.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )
    tree.interface.new_socket(
        name="Curvature", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    tree.interface.new_socket(
        name="Persistence", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    tree.interface.new_socket(
        name="Complexity", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    tree.interface.new_socket(
        name="Boundary", in_out="INPUT", socket_type="NodeSocketFloat"
    )
    tree.interface.new_socket(
        name="B1", in_out="INPUT", socket_type="NodeSocketInt"
    )
    tree.interface.new_socket(
        name="B2", in_out="INPUT", socket_type="NodeSocketInt"
    )
    tree.interface.new_socket(
        name="NestingDepth", in_out="INPUT", socket_type="NodeSocketInt"
    )

    # Set default values on input sockets
    _set_socket_defaults(tree)

    # -----------------------------------------------------------------------
    # Group Input / Output
    # -----------------------------------------------------------------------
    group_in = nodes.new("NodeGroupInput")
    group_in.location = (-1400, 0)

    group_out = nodes.new("NodeGroupOutput")
    group_out.location = (1400, 0)

    # -----------------------------------------------------------------------
    # Join Geometry — collects all geometry streams into final output
    # -----------------------------------------------------------------------
    join_all = nodes.new("GeometryNodeJoinGeometry")
    join_all.location = (1100, 0)
    links.new(join_all.outputs["Geometry"], group_out.inputs["Geometry"])

    # -----------------------------------------------------------------------
    # 1. Spiral Petals — Curve Spiral → Curve to Points → Instance on Points
    # -----------------------------------------------------------------------
    spiral = nodes.new("GeometryNodeCurveSpiral")
    spiral.location = (-1000, 300)
    # Spiral params: 3 rotations, 32+ resolution, curvature-driven radius
    spiral.inputs["Rotations"].default_value = 3.0
    spiral.inputs["Start Radius"].default_value = 0.15
    spiral.inputs["End Radius"].default_value = 0.8
    spiral.inputs["Height"].default_value = 0.0  # flat spiral
    spiral.inputs["Reverse"].default_value = False

    # Use Complexity to drive resolution
    spiral_res = nodes.new("ShaderNodeMath")
    spiral_res.location = (-1200, 200)
    spiral_res.operation = "ADD"
    spiral_res.inputs[0].default_value = 32.0
    links.new(group_in.outputs["Complexity"], spiral_res.inputs[1])

    # Scale complexity from [0,1] → [0,32] for extra resolution
    scale_res = nodes.new("ShaderNodeMath")
    scale_res.location = (-1200, 100)
    scale_res.operation = "MULTIPLY"
    scale_res.inputs[1].default_value = 32.0
    links.new(group_in.outputs["Complexity"], scale_res.inputs[0])
    links.new(scale_res.outputs["Value"], spiral_res.inputs[1])

    # Connect resolution to spiral
    to_int = nodes.new("FunctionNodeFloatToInt")
    to_int.location = (-1050, 200)
    links.new(spiral_res.outputs["Value"], to_int.inputs["Float"])
    links.new(to_int.outputs["Integer"], spiral.inputs["Resolution"])

    # Curvature → End Radius
    curv_radius = nodes.new("ShaderNodeMath")
    curv_radius.location = (-1200, 400)
    curv_radius.operation = "MULTIPLY_ADD"
    curv_radius.inputs[1].default_value = 0.4   # scale
    curv_radius.inputs[2].default_value = 0.6   # base
    links.new(group_in.outputs["Curvature"], curv_radius.inputs[0])
    links.new(curv_radius.outputs["Value"], spiral.inputs["End Radius"])

    # Curve to Points — sample points along spiral for petal placement
    curve_to_pts = nodes.new("GeometryNodeCurveToPoints")
    curve_to_pts.location = (-700, 300)
    curve_to_pts.mode = "COUNT"
    curve_to_pts.inputs["Count"].default_value = 9  # 9 petals
    links.new(spiral.outputs["Curve"], curve_to_pts.inputs["Curve"])

    # Petal dome: ico sphere scaled flat (petal shape)
    petal_mesh = nodes.new("GeometryNodeMeshIcoSphere")
    petal_mesh.location = (-700, 100)
    petal_mesh.inputs["Radius"].default_value = 0.35
    petal_mesh.inputs["Subdivisions"].default_value = 3

    # Scale petal: flatten into dome shape driven by curvature
    petal_scale = nodes.new("GeometryNodeTransform")
    petal_scale.location = (-500, 100)
    links.new(petal_mesh.outputs["Mesh"], petal_scale.inputs["Geometry"])
    # Flatten Z for dome shape: base 0.15, + curvature * 0.2
    curv_dome = nodes.new("ShaderNodeMath")
    curv_dome.location = (-700, -50)
    curv_dome.operation = "MULTIPLY_ADD"
    curv_dome.inputs[1].default_value = 0.2
    curv_dome.inputs[2].default_value = 0.15
    links.new(group_in.outputs["Curvature"], curv_dome.inputs[0])

    # Combine XYZ for petal scale (X=1.0, Y=1.2, Z=dome)
    petal_scale_vec = nodes.new("ShaderNodeCombineXYZ")
    petal_scale_vec.location = (-500, -50)
    petal_scale_vec.inputs["X"].default_value = 1.0
    petal_scale_vec.inputs["Y"].default_value = 1.2
    links.new(curv_dome.outputs["Value"], petal_scale_vec.inputs["Z"])
    links.new(
        petal_scale_vec.outputs["Vector"], petal_scale.inputs["Scale"]
    )

    # Instance petals on spiral points
    instance_petals = nodes.new("GeometryNodeInstanceOnPoints")
    instance_petals.location = (-300, 300)
    links.new(
        curve_to_pts.outputs["Points"], instance_petals.inputs["Points"]
    )
    links.new(
        petal_scale.outputs["Geometry"], instance_petals.inputs["Instance"]
    )
    # Use tangent rotation from curve for natural petal alignment
    links.new(
        curve_to_pts.outputs["Rotation"],
        instance_petals.inputs["Rotation"],
    )

    # Set material index 0 (petal glass) on instances — retain instances
    # per Blender 5.0 best practice for memory efficiency
    set_mat_petal = nodes.new("GeometryNodeSetMaterialIndex")
    set_mat_petal.location = (100, 300)
    set_mat_petal.inputs["Material Index"].default_value = 0
    links.new(
        instance_petals.outputs["Instances"],
        set_mat_petal.inputs["Geometry"],
    )
    links.new(set_mat_petal.outputs["Geometry"], join_all.inputs["Geometry"])

    # -----------------------------------------------------------------------
    # 2. Nested Shells — Repeat Zone driven by persistence / NestingDepth
    # -----------------------------------------------------------------------
    _build_nested_shells(tree, nodes, links, group_in, join_all)

    # -----------------------------------------------------------------------
    # 3. Torus ribbons — B1-driven count
    # -----------------------------------------------------------------------
    _build_torus_ribbons(tree, nodes, links, group_in, join_all)

    # -----------------------------------------------------------------------
    # 4. Void chambers — B2-driven inverted ico spheres
    # -----------------------------------------------------------------------
    _build_void_chambers(tree, nodes, links, group_in, join_all)

    # -----------------------------------------------------------------------
    # 5. Plasma core + glow sphere
    # -----------------------------------------------------------------------
    _build_plasma_core(tree, nodes, links, group_in, join_all)

    return tree


def _set_socket_defaults(tree):
    """Set default values on input interface sockets."""
    for item in tree.interface.items_tree:
        if item.in_out == "INPUT":
            if item.name == "Curvature":
                item.default_value = 0.5
                item.min_value = 0.0
                item.max_value = 1.0
            elif item.name == "Persistence":
                item.default_value = 0.5
                item.min_value = 0.0
                item.max_value = 1.0
            elif item.name == "Complexity":
                item.default_value = 0.5
                item.min_value = 0.0
                item.max_value = 1.0
            elif item.name == "Boundary":
                item.default_value = 0.5
                item.min_value = 0.0
                item.max_value = 1.0
            elif item.name == "B1":
                item.default_value = 2
                item.min_value = 0
                item.max_value = 5
            elif item.name == "B2":
                item.default_value = 1
                item.min_value = 0
                item.max_value = 3
            elif item.name == "NestingDepth":
                item.default_value = 2
                item.min_value = 1
                item.max_value = 5


def _build_nested_shells(_tree, nodes, links, group_in, join_all):
    """Build the Repeat Zone for persistence-driven nested glass shells.

    Each iteration scales 0.72x and rotates slightly, creating recursive
    nesting like Russian dolls — the big upgrade over single-shell.
    """
    # Create Repeat Zone (input + output pair)
    repeat_in = nodes.new("GeometryNodeRepeatInput")
    repeat_in.location = (-200, -100)

    repeat_out = nodes.new("GeometryNodeRepeatOutput")
    repeat_out.location = (600, -100)

    # Pair them
    repeat_in.pair_with_output(repeat_out)

    # Connect NestingDepth to iterations
    links.new(group_in.outputs["NestingDepth"], repeat_in.inputs["Iterations"])

    # Add a Geometry socket to the repeat zone
    # In Blender 4.x, Repeat Zone starts with no sockets — we add one
    repeat_out.repeat_items.new("GEOMETRY", "ShellGeo")

    # Inside the repeat zone: create an ico sphere shell, scale down, rotate
    # Each iteration produces a shell at decreasing scale

    # Ico sphere as shell template
    shell_mesh = nodes.new("GeometryNodeMeshIcoSphere")
    shell_mesh.location = (0, -200)
    shell_mesh.inputs["Radius"].default_value = 0.5
    shell_mesh.inputs["Subdivisions"].default_value = 4

    # Scale per iteration: 0.72^iteration — done via Transform inside loop
    # The repeat zone body transforms geometry each iteration
    shell_transform = nodes.new("GeometryNodeTransform")
    shell_transform.location = (200, -200)
    shell_transform.inputs["Scale"].default_value = (0.72, 0.72, 0.72)
    # Slight rotation per nesting level for visual variety
    shell_transform.inputs["Rotation"].default_value = (0.15, 0.12, 0.08)

    links.new(shell_mesh.outputs["Mesh"], shell_transform.inputs["Geometry"])

    # Join the new shell with accumulated geometry from previous iterations
    join_shells = nodes.new("GeometryNodeJoinGeometry")
    join_shells.location = (400, -100)

    # Connect repeat zone input geometry (accumulated) to join
    links.new(repeat_in.outputs["ShellGeo"], join_shells.inputs["Geometry"])
    # Connect new shell to join
    links.new(
        shell_transform.outputs["Geometry"], join_shells.inputs["Geometry"]
    )

    # Output accumulated geometry back to repeat zone
    links.new(join_shells.outputs["Geometry"], repeat_out.inputs["ShellGeo"])

    # Set material index 1 (shell glass) on output
    set_mat_shell = nodes.new("GeometryNodeSetMaterialIndex")
    set_mat_shell.location = (800, -100)
    set_mat_shell.inputs["Material Index"].default_value = 1
    links.new(
        repeat_out.outputs["ShellGeo"], set_mat_shell.inputs["Geometry"]
    )
    links.new(
        set_mat_shell.outputs["Geometry"], join_all.inputs["Geometry"]
    )


def _build_torus_ribbons(_tree, nodes, links, group_in, join_all):
    """Build B1-driven torus ribbon instances.

    Blender 5.0: GeometryNodeMeshTorus removed — build torus via
    Curve Circle (major) + Curve to Mesh with circle profile (minor).
    """
    # Torus = sweep a small circle (profile) along a large circle (path)
    # Path circle: major radius
    torus_path = nodes.new("GeometryNodeCurvePrimitiveCircle")
    torus_path.location = (-400, -500)
    torus_path.mode = "RADIUS"
    torus_path.inputs["Radius"].default_value = 0.5
    torus_path.inputs["Resolution"].default_value = 96

    # Profile circle: minor radius (thin ribbon)
    torus_profile = nodes.new("GeometryNodeCurvePrimitiveCircle")
    torus_profile.location = (-400, -600)
    torus_profile.mode = "RADIUS"
    torus_profile.inputs["Radius"].default_value = 0.015
    torus_profile.inputs["Resolution"].default_value = 12

    # Curve to Mesh: sweep profile along path → torus
    torus_mesh = nodes.new("GeometryNodeCurveToMesh")
    torus_mesh.location = (-200, -500)
    links.new(torus_path.outputs["Curve"], torus_mesh.inputs["Curve"])
    links.new(torus_profile.outputs["Curve"], torus_mesh.inputs["Profile Curve"])

    # Create points on a circle to instance tori at
    torus_circle = nodes.new("GeometryNodeMeshCircle")
    torus_circle.location = (-400, -750)
    torus_circle.inputs["Radius"].default_value = 0.01  # tiny, just for points
    # B1 drives how many torus instances
    links.new(group_in.outputs["B1"], torus_circle.inputs["Vertices"])

    # Convert mesh to points (one per vertex)
    torus_pts = nodes.new("GeometryNodeMeshToPoints")
    torus_pts.location = (-200, -750)
    links.new(torus_circle.outputs["Mesh"], torus_pts.inputs["Mesh"])

    # Index for rotation variation
    torus_idx = nodes.new("GeometryNodeInputIndex")
    torus_idx.location = (-400, -900)

    # Rotation from index: spread tori at different angles
    idx_to_float = nodes.new("ShaderNodeMath")
    idx_to_float.location = (-200, -900)
    idx_to_float.operation = "MULTIPLY"
    idx_to_float.inputs[1].default_value = 0.4

    links.new(torus_idx.outputs["Index"], idx_to_float.inputs[0])

    torus_rot = nodes.new("ShaderNodeCombineXYZ")
    torus_rot.location = (0, -900)
    torus_rot.inputs["X"].default_value = math.pi / 3
    links.new(idx_to_float.outputs["Value"], torus_rot.inputs["Y"])
    links.new(idx_to_float.outputs["Value"], torus_rot.inputs["Z"])

    # Instance tori on points
    instance_tori = nodes.new("GeometryNodeInstanceOnPoints")
    instance_tori.location = (100, -500)
    links.new(torus_pts.outputs["Points"], instance_tori.inputs["Points"])
    links.new(torus_mesh.outputs["Mesh"], instance_tori.inputs["Instance"])
    links.new(
        torus_rot.outputs["Vector"], instance_tori.inputs["Rotation"]
    )

    # Material index 0 (petal glass for tori too) — retain instances
    set_mat_tori = nodes.new("GeometryNodeSetMaterialIndex")
    set_mat_tori.location = (300, -500)
    set_mat_tori.inputs["Material Index"].default_value = 0
    links.new(
        instance_tori.outputs["Instances"],
        set_mat_tori.inputs["Geometry"],
    )
    links.new(set_mat_tori.outputs["Geometry"], join_all.inputs["Geometry"])


def _build_void_chambers(_tree, nodes, links, group_in, join_all):
    """Build B2-driven inverted ico sphere void chambers."""
    # Ico sphere
    void_mesh = nodes.new("GeometryNodeMeshIcoSphere")
    void_mesh.location = (-200, -900)
    void_mesh.inputs["Radius"].default_value = 0.15
    void_mesh.inputs["Subdivisions"].default_value = 3

    # Flip normals (invert) for enclosed-void look
    flip = nodes.new("GeometryNodeFlipFaces")
    flip.location = (0, -900)
    links.new(void_mesh.outputs["Mesh"], flip.inputs["Mesh"])

    # Points for void placement — circle of B2 vertices
    void_circle = nodes.new("GeometryNodeMeshCircle")
    void_circle.location = (-400, -900)
    void_circle.inputs["Radius"].default_value = 0.35
    links.new(group_in.outputs["B2"], void_circle.inputs["Vertices"])

    void_pts = nodes.new("GeometryNodeMeshToPoints")
    void_pts.location = (-200, -1000)
    links.new(void_circle.outputs["Mesh"], void_pts.inputs["Mesh"])

    # Instance voids
    instance_voids = nodes.new("GeometryNodeInstanceOnPoints")
    instance_voids.location = (200, -900)
    links.new(void_pts.outputs["Points"], instance_voids.inputs["Points"])
    links.new(flip.outputs["Mesh"], instance_voids.inputs["Instance"])

    # Material index 1 (shell glass) — retain instances
    set_mat_void = nodes.new("GeometryNodeSetMaterialIndex")
    set_mat_void.location = (400, -900)
    set_mat_void.inputs["Material Index"].default_value = 1
    links.new(
        instance_voids.outputs["Instances"],
        set_mat_void.inputs["Geometry"],
    )
    links.new(set_mat_void.outputs["Geometry"], join_all.inputs["Geometry"])


def _build_plasma_core(_tree, nodes, links, group_in, join_all):
    """Build plasma core (emissive) + glow sphere."""
    # Small bright core
    core_mesh = nodes.new("GeometryNodeMeshIcoSphere")
    core_mesh.location = (-200, -1300)
    core_mesh.inputs["Radius"].default_value = 0.1
    core_mesh.inputs["Subdivisions"].default_value = 3

    # Boundary drives core size via scale
    core_scale_math = nodes.new("ShaderNodeMath")
    core_scale_math.location = (-200, -1400)
    core_scale_math.operation = "MULTIPLY_ADD"
    core_scale_math.inputs[1].default_value = 0.5  # boundary * 0.5
    core_scale_math.inputs[2].default_value = 0.8  # + 0.8 base scale
    links.new(group_in.outputs["Boundary"], core_scale_math.inputs[0])

    core_scale_vec = nodes.new("ShaderNodeCombineXYZ")
    core_scale_vec.location = (0, -1400)
    links.new(core_scale_math.outputs["Value"], core_scale_vec.inputs["X"])
    links.new(core_scale_math.outputs["Value"], core_scale_vec.inputs["Y"])
    links.new(core_scale_math.outputs["Value"], core_scale_vec.inputs["Z"])

    core_transform = nodes.new("GeometryNodeTransform")
    core_transform.location = (0, -1300)
    links.new(core_mesh.outputs["Mesh"], core_transform.inputs["Geometry"])
    links.new(
        core_scale_vec.outputs["Vector"], core_transform.inputs["Scale"]
    )

    # Material index 2 (plasma)
    set_mat_core = nodes.new("GeometryNodeSetMaterialIndex")
    set_mat_core.location = (200, -1300)
    set_mat_core.inputs["Material Index"].default_value = 2
    links.new(
        core_transform.outputs["Geometry"], set_mat_core.inputs["Geometry"]
    )
    links.new(
        set_mat_core.outputs["Geometry"], join_all.inputs["Geometry"]
    )

    # Larger glow sphere (lower intensity, larger area)
    glow_mesh = nodes.new("GeometryNodeMeshIcoSphere")
    glow_mesh.location = (-200, -1600)
    glow_mesh.inputs["Radius"].default_value = 0.4
    glow_mesh.inputs["Subdivisions"].default_value = 3

    # Material index 3 (plasma glow)
    set_mat_glow = nodes.new("GeometryNodeSetMaterialIndex")
    set_mat_glow.location = (200, -1600)
    set_mat_glow.inputs["Material Index"].default_value = 3
    links.new(glow_mesh.outputs["Mesh"], set_mat_glow.inputs["Geometry"])
    links.new(
        set_mat_glow.outputs["Geometry"], join_all.inputs["Geometry"]
    )
