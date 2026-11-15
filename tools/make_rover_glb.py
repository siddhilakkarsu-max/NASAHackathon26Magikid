"""
Make the low-poly vehicle models the map shows where you hover over a route, one per vehicle:
  frontend/rover.glb      six-wheeled robotic rover (Perseverance/Curiosity-like, ~3 m)
  frontend/astronaut.glb  suited astronaut on foot (~1.9 m)
  frontend/bike.glb       2-wheel scout bike with a cargo box
  frontend/lrv.glb        4-wheel open rover (Apollo LRV-like)
  frontend/buggy.glb      pressurized 6-wheel buggy
Built from boxes, cylinders and spheres, no dependencies beyond numpy.

    python tools/make_rover_glb.py

Model axes (glTF): +X = front, +Y = up, +Z = right side. Units: metres.
"""
import json
import struct
from pathlib import Path

import numpy as np

OUT_DIR = Path(__file__).resolve().parent.parent / "frontend"

COLORS = {                                # base colour, metallic, roughness
    "body": ([0.90, 0.90, 0.88], 0.1, 0.6),
    "deck": ([0.80, 0.62, 0.28], 0.6, 0.4),    # gold insulation
    "dark": ([0.16, 0.16, 0.18], 0.2, 0.7),
    "wheel": ([0.33, 0.33, 0.35], 0.5, 0.6),
    "accent": ([0.88, 0.44, 0.23], 0.1, 0.5),  # matches the app's orange
    "glass": ([0.10, 0.16, 0.22], 0.3, 0.1),
    "visor": ([0.85, 0.65, 0.20], 0.9, 0.15),   # gold sun visor
    "panel": ([0.12, 0.18, 0.40], 0.4, 0.3),    # solar cells
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


def sphere(c, radius, n=14):
    """UV sphere."""
    c = np.array(c, float)
    pos, idx = [], []
    for i in range(n + 1):
        th = np.pi * i / n
        for j in range(2 * n):
            ph = 2 * np.pi * j / (2 * n)
            pos.append([np.sin(th) * np.cos(ph), np.cos(th), np.sin(th) * np.sin(ph)])
    for i in range(n):
        for j in range(2 * n):
            a, b = i * 2 * n + j, i * 2 * n + (j + 1) % (2 * n)
            idx += [a, a + 2 * n, b, b, a + 2 * n, b + 2 * n]
    nrm = np.array(pos)
    return c + nrm * radius, nrm, np.array(idx)


def astronaut():
    parts = []
    add = lambda mat, geom: parts.append((mat, geom))
    for z in (-0.13, 0.13):
        add("body", box((0.0, 0.42, z), (0.2, 0.84, 0.18)))          # legs
        add("dark", box((0.04, 0.05, z), (0.3, 0.1, 0.2)))            # boots
        add("body", box((0.0, 1.15, z * 2.8), (0.16, 0.62, 0.15)))   # arms
    add("body", box((0.0, 1.22, 0.0), (0.36, 0.72, 0.5)))             # torso
    add("body", box((-0.33, 1.25, 0.0), (0.3, 0.7, 0.46)))            # life-support backpack
    add("accent", box((0.19, 1.3, 0.0), (0.02, 0.18, 0.28)))          # chest controls
    add("body", sphere((0.03, 1.78, 0.0), 0.2))                       # helmet
    add("visor", box((0.17, 1.79, 0.0), (0.08, 0.2, 0.26)))           # visor
    return parts


def bike():
    parts = []
    add = lambda mat, geom: parts.append((mat, geom))
    for x in (0.75, -0.75):
        add("wheel", cylinder((x, 0.38, 0.0), 0.38, 0.22, axis=2))    # balloon wheels
        add("dark", cylinder((x, 0.38, 0.0), 0.12, 0.3, axis=2))      # hub motors
    add("body", box((0.0, 0.72, 0.0), (1.3, 0.16, 0.16)))             # frame
    add("body", box((0.62, 0.95, 0.0), (0.1, 0.55, 0.1)))             # fork
    add("dark", box((0.62, 1.22, 0.0), (0.08, 0.06, 0.7)))            # handlebar
    add("dark", box((-0.15, 0.95, 0.0), (0.45, 0.1, 0.3)))            # seat
    add("accent", box((-0.62, 0.95, 0.0), (0.45, 0.35, 0.5)))         # cargo box
    add("panel", box((-0.62, 1.14, 0.0), (0.5, 0.03, 0.55)))          # solar lid
    return parts


def lrv():
    parts = []
    add = lambda mat, geom: parts.append((mat, geom))
    add("body", box((0.0, 0.62, 0.0), (3.0, 0.12, 1.5)))              # flat chassis
    for x in (1.15, -1.15):
        for z in (-0.95, 0.95):
            add("wheel", cylinder((x, 0.4, z), 0.4, 0.25, axis=2))    # wire-mesh wheels
            add("deck", box((x, 0.88, z * 0.9), (0.9, 0.06, 0.32)))   # gold fenders
    for z in (-0.38, 0.38):
        add("dark", box((0.1, 0.78, z), (0.55, 0.2, 0.55)))           # seats
        add("dark", box((-0.15, 1.05, z), (0.08, 0.55, 0.55)))        # seat backs
    add("dark", box((0.75, 0.95, 0.0), (0.2, 0.5, 0.6)))              # control console
    add("body", cylinder((0.95, 1.4, -0.45), 0.03, 1.2, axis=1))      # antenna mast
    add("body", cylinder((0.95, 2.0, -0.45), 0.5, 0.04, axis=1))      # umbrella high-gain antenna
    add("deck", box((-1.25, 0.85, 0.0), (0.5, 0.4, 1.1)))             # tool / sample rack
    return parts


def buggy():
    parts = []
    add = lambda mat, geom: parts.append((mat, geom))
    add("body", box((0.0, 1.55, 0.0), (4.2, 1.9, 2.4)))               # pressurized cabin
    add("glass", box((2.12, 1.85, 0.0), (0.06, 0.8, 2.0)))            # front windows
    for z in (-1.21, 1.21):
        add("glass", box((1.3, 1.9, z), (0.9, 0.5, 0.04)))            # side windows
    add("accent", box((0.0, 0.7, 0.0), (4.4, 0.25, 2.5)))             # orange skirt
    add("dark", box((-2.15, 1.35, 0.0), (0.12, 1.2, 1.0)))            # suit ports / hatch
    add("panel", box((-0.4, 2.55, 0.0), (3.0, 0.06, 2.2)))            # solar roof
    add("body", cylinder((1.4, 2.8, 0.7), 0.28, 0.04, axis=1))        # antenna dish
    for x in (1.5, 0.0, -1.5):
        for z in (-1.35, 1.35):
            add("wheel", cylinder((x, 0.5, z), 0.5, 0.4, axis=2))
    return parts


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


MODELS = {"rover": rover, "astronaut": astronaut, "bike": bike, "lrv": lrv, "buggy": buggy}

if __name__ == "__main__":
    for name, make in MODELS.items():
        out = OUT_DIR / f"{name}.glb"
        size = write_glb(make(), out)
        print(f"wrote {out.name} ({size / 1024:.1f} KB)")
