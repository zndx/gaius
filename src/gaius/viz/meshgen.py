"""Pure numpy mesh generators for LuxCore card visualizations.

Each function returns (vertices: ndarray[N,3], faces: ndarray[M,3]) where
vertices are float32 and faces are int32 triangle indices. No Blender
dependency -- meshes feed directly into pyluxcore inlinedmesh definitions.
"""

from __future__ import annotations

import math

import numpy as np


def make_ico_sphere(
    radius: float = 1.0,
    subdivisions: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Recursive icosahedron subdivision (Loop-style).

    Starts from a 12-vertex icosahedron and subdivides each triangle into
    4 sub-triangles, projecting new vertices onto the sphere surface.

    Args:
        radius: Sphere radius.
        subdivisions: Number of subdivision passes (0=icosahedron, 3=642 verts).

    Returns:
        (vertices [N,3] float32, faces [M,3] int32)
    """
    # Golden ratio
    t = (1.0 + math.sqrt(5.0)) / 2.0

    # 12 vertices of a unit icosahedron
    verts = [
        (-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0),
        (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
        (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1),
    ]

    # 20 triangular faces
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]

    # Midpoint cache for subdivision
    mid_cache: dict[tuple[int, int], int] = {}

    def _midpoint(i1: int, i2: int) -> int:
        key = (min(i1, i2), max(i1, i2))
        if key in mid_cache:
            return mid_cache[key]
        p1 = verts[i1]
        p2 = verts[i2]
        mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, (p1[2] + p2[2]) / 2)
        # Project onto unit sphere
        length = math.sqrt(mid[0] ** 2 + mid[1] ** 2 + mid[2] ** 2)
        mid = (mid[0] / length, mid[1] / length, mid[2] / length)
        idx = len(verts)
        verts.append(mid)
        mid_cache[key] = idx
        return idx

    for _ in range(subdivisions):
        new_faces = []
        mid_cache.clear()
        for tri in faces:
            a, b, c = tri
            ab = _midpoint(a, b)
            bc = _midpoint(b, c)
            ca = _midpoint(c, a)
            new_faces.extend([
                (a, ab, ca),
                (b, bc, ab),
                (c, ca, bc),
                (ab, bc, ca),
            ])
        faces = new_faces

    # Scale to requested radius
    v = np.array(verts, dtype=np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms = np.where(norms < 1e-10, 1.0, norms)
    v = v / norms * radius

    f = np.array(faces, dtype=np.int32)
    return v, f


def make_petal_disk(
    radius: float = 1.0,
    segments: int = 48,
    dome_factor: float = 0.2,
    twist_angle: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Triangle-fan disk with dome deformation and twist.

    Matches Blender petal construction: filled circle -> cast to sphere (dome)
    -> twist deformation. Solidify is handled by the renderer adding thickness
    to the inlinedmesh (or we generate front/back offset surfaces).

    Args:
        radius: Outer radius.
        segments: Number of outer vertices.
        dome_factor: How much to dome upward (0=flat, 1=hemisphere).
        twist_angle: Twist deformation angle in radians.

    Returns:
        (vertices [N,3] float32, faces [M,3] int32)
    """
    # Center vertex
    verts = [(0.0, 0.0, 0.0)]

    # Outer ring
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        verts.append((x, y, 0.0))

    # Triangle fan faces
    faces = []
    for i in range(segments):
        next_i = (i % segments) + 1
        next_j = (next_i % segments) + 1
        faces.append((0, next_i, next_j if next_j <= segments else 1))

    v = np.array(verts, dtype=np.float32)

    # Dome deformation: push z based on distance from center
    for i in range(1, len(v)):
        dist = math.sqrt(v[i, 0] ** 2 + v[i, 1] ** 2)
        normalized_dist = dist / radius if radius > 0 else 0
        # Spherical dome: z = dome_factor * sqrt(1 - r^2)
        r_clamped = min(normalized_dist, 0.999)
        v[i, 2] = dome_factor * radius * math.sqrt(1.0 - r_clamped ** 2)

    # Twist deformation: rotate each vertex around Z by twist_angle * (dist/radius)
    if abs(twist_angle) > 0.01:
        for i in range(1, len(v)):
            dist = math.sqrt(v[i, 0] ** 2 + v[i, 1] ** 2)
            t = dist / radius if radius > 0 else 0
            rot = twist_angle * t
            cos_r, sin_r = math.cos(rot), math.sin(rot)
            x, y = v[i, 0], v[i, 1]
            v[i, 0] = x * cos_r - y * sin_r
            v[i, 1] = x * sin_r + y * cos_r

    # Add thickness by duplicating vertices with offset (solidify equivalent)
    thickness = 0.02 * radius
    n_original = len(v)
    bottom_verts = v.copy()
    bottom_verts[:, 2] -= thickness
    v = np.vstack([v, bottom_verts])

    # Bottom faces (reversed winding)
    bottom_faces = []
    for face in faces:
        bottom_faces.append((face[0] + n_original, face[2] + n_original, face[1] + n_original))

    # Side faces connecting top ring to bottom ring
    side_faces = []
    for i in range(segments):
        top_a = i + 1
        top_b = (i + 1) % segments + 1
        bot_a = top_a + n_original
        bot_b = top_b + n_original
        side_faces.append((top_a, bot_a, bot_b))
        side_faces.append((top_a, bot_b, top_b))

    all_faces = faces + bottom_faces + side_faces
    f = np.array(all_faces, dtype=np.int32)
    return v, f


def make_torus(
    major_r: float = 0.4,
    minor_r: float = 0.02,
    major_segs: int = 96,
    minor_segs: int = 12,
) -> tuple[np.ndarray, np.ndarray]:
    """Parametric torus mesh.

    Args:
        major_r: Distance from center of torus to center of tube.
        minor_r: Radius of the tube.
        major_segs: Segments around the major circle.
        minor_segs: Segments around the tube cross-section.

    Returns:
        (vertices [N,3] float32, faces [M,3] int32)
    """
    verts = []
    for i in range(major_segs):
        theta = 2 * math.pi * i / major_segs
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        for j in range(minor_segs):
            phi = 2 * math.pi * j / minor_segs
            cos_p, sin_p = math.cos(phi), math.sin(phi)
            x = (major_r + minor_r * cos_p) * cos_t
            y = (major_r + minor_r * cos_p) * sin_t
            z = minor_r * sin_p
            verts.append((x, y, z))

    faces = []
    for i in range(major_segs):
        next_i = (i + 1) % major_segs
        for j in range(minor_segs):
            next_j = (j + 1) % minor_segs
            v0 = i * minor_segs + j
            v1 = next_i * minor_segs + j
            v2 = next_i * minor_segs + next_j
            v3 = i * minor_segs + next_j
            faces.append((v0, v1, v2))
            faces.append((v0, v2, v3))

    return np.array(verts, dtype=np.float32), np.array(faces, dtype=np.int32)


def make_cylinder(
    radius: float = 0.01,
    depth: float = 0.5,
    segments: int = 12,
) -> tuple[np.ndarray, np.ndarray]:
    """Capped cylinder mesh.

    Args:
        radius: Cylinder radius.
        depth: Total height (centered at origin).
        segments: Number of radial segments.

    Returns:
        (vertices [N,3] float32, faces [M,3] int32)
    """
    half_h = depth / 2
    verts = []
    faces = []

    # Bottom center
    verts.append((0.0, 0.0, -half_h))
    # Bottom ring
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        verts.append((radius * math.cos(angle), radius * math.sin(angle), -half_h))
    # Top center
    top_center = len(verts)
    verts.append((0.0, 0.0, half_h))
    # Top ring
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        verts.append((radius * math.cos(angle), radius * math.sin(angle), half_h))

    # Bottom cap faces
    for i in range(segments):
        next_i = (i + 1) % segments
        faces.append((0, next_i + 1, i + 1))

    # Top cap faces
    for i in range(segments):
        next_i = (i + 1) % segments
        faces.append((top_center, top_center + 1 + i, top_center + 1 + next_i))

    # Side faces
    for i in range(segments):
        next_i = (i + 1) % segments
        bot_a = i + 1
        bot_b = next_i + 1
        top_a = top_center + 1 + i
        top_b = top_center + 1 + next_i
        faces.append((bot_a, bot_b, top_b))
        faces.append((bot_a, top_b, top_a))

    return np.array(verts, dtype=np.float32), np.array(faces, dtype=np.int32)


def apply_transform(verts: np.ndarray, xf: dict) -> np.ndarray:
    """Apply position + rotation + scale from grammar transform dict.

    Rotation order: X -> Y -> Z (Euler XYZ, matches Blender default).

    Args:
        verts: Vertex array [N, 3].
        xf: Transform dict with x, y, z, rx, ry, rz, scale keys.

    Returns:
        Transformed vertex array [N, 3].
    """
    s = xf.get("scale", 1.0)
    rx, ry, rz = xf.get("rx", 0), xf.get("ry", 0), xf.get("rz", 0)

    # Scale
    v = verts * s

    # Rotation matrices
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)

    # Combined rotation matrix (XYZ order)
    rot = np.array([
        [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
        [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
        [-sy,     sx * cy,                cx * cy],
    ], dtype=np.float32)

    v = v @ rot.T

    # Translation
    v[:, 0] += xf.get("x", 0)
    v[:, 1] += xf.get("y", 0)
    v[:, 2] += xf.get("z", 0)

    return v


def compute_normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Compute smooth vertex normals via area-weighted face normal averaging.

    Args:
        verts: Vertex positions [N, 3].
        faces: Triangle indices [M, 3].

    Returns:
        Vertex normals [N, 3], normalized.
    """
    normals = np.zeros_like(verts, dtype=np.float32)

    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]

    # Face normals (not normalized -- magnitude = 2x triangle area)
    face_normals = np.cross(v1 - v0, v2 - v0)

    # Accumulate face normals onto vertices
    for axis in range(3):
        np.add.at(normals[:, axis], faces[:, 0], face_normals[:, axis])
        np.add.at(normals[:, axis], faces[:, 1], face_normals[:, axis])
        np.add.at(normals[:, axis], faces[:, 2], face_normals[:, axis])

    # Normalize
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths = np.where(lengths < 1e-10, 1.0, lengths)
    normals = normals / lengths

    return normals
