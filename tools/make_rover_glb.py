"""
Make frontend/rover.glb: a small low-poly six-wheeled rover (Perseverance-like proportions, ~3 m long) that the
map shows where you hover over a route. Built from boxes and cylinders, no dependencies beyond numpy.

    python tools/make_rover_glb.py

Model axes (glTF): +X = front of the rover, +Y = up, +Z = right side. Units: metres.
"""
import json
import struct
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent.parent / "frontend" / "rover.glb"

COLORS = {                                # base colour, metallic, roughness
    "body": ([0.90, 0.90, 0.88], 0.1, 0.6),
    "deck": ([0.80, 0.62, 0.28], 0.6, 0.4),    # gold insulation
    "dark": ([0.16, 0.16, 0.18], 0.2, 0.7),
    "wheel": ([0.33, 0.33, 0.35], 0.5, 0.6),
    "accent": ([0.88, 0.44, 0.23], 0.1, 0.5),  # matches the app's orange
}


def box(c, size):
    """Axis-aligned box: 24 vertices (flat normals), 12 triangles."""
    c, h = np.array(c, float), np.array(size, float) / 2
    pos, nrm, idx = [], [], []
    for axis in range(3):
        for sign in (-1, 1):
            n = np.zeros(3); n[axis] = sign
            u, v = [a for a in range(3) if a != axis]
            quad = []
            for du, dv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                p = c.copy(); p[axis] += sign * h[axis]; p[u] += du * h[u]; p[v] += dv * h[v]
                quad.append(p)
            base = len(pos)
            pos += quad; nrm += [n] * 4
            idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return np.array(pos), np.array(nrm), np.array(idx)


def cylinder(c, radius, length, axis, n=20):
    """Closed cylinder along axis 0/1/2: side with smooth normals + two caps."""
    c = np.array(c, float)
    u, v = [a for a in range(3) if a != axis]
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.zeros((n, 3)); ring[:, u] = np.cos(ang); ring[:, v] = np.sin(ang)
    pos, nrm, idx = [], [], []
    for end in (-1, 1):                                   # side vertices: bottom ring then top ring
        p = c + ring * radius; p[:, axis] += end * length / 2
        pos += list(p); nrm += list(ring)
    for i in range(n):
        j = (i + 1) % n
        idx += [i, j, n + j, i, n + j, n + i]
    for end in (-1, 1):                                   # caps
        ax = np.zeros(3); ax[axis] = end
        centre = c.copy(); centre[axis] += end * length / 2
        base = len(pos)
        pos.append(centre); nrm.append(ax)
        p = c + ring * radius; p[:, axis] += end * length / 2
        pos += list(p); nrm += [ax] * n
        for i in range(n):
            idx += [base, base + 1 + i, base + 1 + (i + 1) % n]
    return np.array(pos), np.array(nrm), np.array(idx)


def rover():
    parts = []                                            # (material, (positions, normals, indices))
    add = lambda mat, geom: parts.append((mat, geom))
    add("body", box((0.0, 0.95, 0.0), (2.2, 0.55, 1.6)))              # chassis
    add("deck", box((-0.1, 1.28, 0.0), (2.0, 0.1, 1.7)))              # top deck
    add("dark", cylinder((-1.3, 1.15, 0.0), 0.3, 0.75, axis=0))      # power unit (MMRTG) at the back
    add("body", cylinder((0.75, 1.85, 0.5), 0.06, 1.1, axis=1))       # mast
    add("dark", box((0.82, 2.45, 0.5), (0.3, 0.22, 0.5)))             # mast camera head
    add("accent", box((0.97, 2.45, 0.5), (0.02, 0.08, 0.36)))         # camera "eyes" strip (front)
    add("body", cylinder((-0.55, 1.5, -0.55), 0.32, 0.05, axis=1))    # high-gain antenna dish
    add("body", box((1.45, 0.95, -0.35), (0.7, 0.09, 0.09)))          # robotic arm
    add("dark", box((1.85, 0.85, -0.35), (0.22, 0.25, 0.22)))         # arm turret
    for z in (-0.95, 0.95):                                           # rocker-bogie beams
        add("dark", box((0.0, 0.62, z), (2.0, 0.08, 0.08)))
        for x in (0.95, 0.0, -0.95):
            add("dark", box((x, 0.45, z), (0.07, 0.35, 0.07)))       # legs
            add("wheel", cylinder((x, 0.27, z * 1.05), 0.27, 0.26, axis=2))
    return parts


def write_glb(parts, path):
    mats = list(COLORS)
    blob, views, accessors, prims = bytearray(), [], [], []

    def add_view(data, target):
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target})
        blob.extend(data)
        return len(views) - 1

    for mat, (pos, nrm, idx) in parts:
        pos, nrm = pos.astype("<f4"), (nrm / np.linalg.norm(nrm, axis=1, keepdims=True)).astype("<f4")
        pv = add_view(pos.tobytes(), 34962)
        nv = add_view(nrm.tobytes(), 34962)
        iv = add_view(idx.astype("<u2").tobytes(), 34963)
        accessors += [
            {"bufferView": pv, "componentType": 5126, "count": len(pos), "type": "VEC3",
             "min": pos.min(axis=0).tolist(), "max": pos.max(axis=0).tolist()},
            {"bufferView": nv, "componentType": 5126, "count": len(nrm), "type": "VEC3"},
            {"bufferView": iv, "componentType": 5123, "count": len(idx), "type": "SCALAR"},
        ]
        a = len(accessors) - 3
        prims.append({"attributes": {"POSITION": a, "NORMAL": a + 1}, "indices": a + 2, "material": mats.index(mat)})
    while len(blob) % 4:
        blob.append(0)
    gltf = {
        "asset": {"version": "2.0", "generator": "make_rover_glb.py (Marswalk Planner)"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "rover"}],
        "meshes": [{"name": "rover", "primitives": prims}],
        "materials": [{"name": m, "doubleSided": True, "pbrMetallicRoughness": {
            "baseColorFactor": COLORS[m][0] + [1.0], "metallicFactor": COLORS[m][1], "roughnessFactor": COLORS[m][2]}}
            for m in mats],
        "buffers": [{"byteLength": len(blob)}], "bufferViews": views, "accessors": accessors,
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(js), b"JSON")); f.write(js)
        f.write(struct.pack("<I4s", len(blob), b"BIN\x00")); f.write(bytes(blob))
    return total


if __name__ == "__main__":
    size = write_glb(rover(), OUT)
    print(f"wrote {OUT} ({size / 1024:.1f} KB)")
