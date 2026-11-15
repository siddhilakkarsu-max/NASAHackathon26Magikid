"""Build route-playback GLBs with NumPy. Positions are meters, Y up, Z forward."""
import json
import math
import struct
from pathlib import Path

import numpy as np


DEST = Path(__file__).parent / "frontend" / "route_models"
COLORS = {
    "white": "e5ebec", "metal": "9fadb8", "dark": "28323a", "black": "131b23",
    "rubber": "30333a", "gold": "dbab62", "foil": "a97c3e", "visor": "a36021",
    "glass": "386c83", "red": "c54232", "blue": "345f8d", "solar": "263c67",
    "orange": "dc943c", "cream": "e0d1b4",
}


def rotation(axis, angle):
    return [math.sin(angle / 2) * component for component in axis] + [math.cos(angle / 2)]


def box_geometry():
    positions, normals, indices = [], [], []
    for normal in np.vstack((np.eye(3), -np.eye(3))):
        tangent = np.roll(normal, 1)
        bitangent = np.cross(normal, tangent)
        offset = len(positions)
        for u, v in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
            positions.append((normal + tangent * u + bitangent * v) * .5)
            normals.append(normal)
        indices.extend(offset + i for i in (0, 1, 2, 0, 2, 3))
    return positions, normals, indices


def sphere_geometry():
    positions, normals, indices = [], [], []
    slices, rings = 16, 10
    for row in range(rings + 1):
        latitude = math.pi * (row / rings - .5)
        for col in range(slices):
            longitude = math.tau * col / slices
            normal = np.array((math.cos(latitude) * math.cos(longitude), math.sin(latitude),
                               math.cos(latitude) * math.sin(longitude)))
            positions.append(normal * .5)
            normals.append(normal)
            if row < rings:
                a = row * slices + col
                b = row * slices + (col + 1) % slices
                indices.extend((a, a + slices, b + slices, a, b + slices, b))
    return positions, normals, indices


def cylinder_geometry():
    positions, normals, indices = [], [], []
    sides = 16
    ring = [(math.cos(i * math.tau / sides), math.sin(i * math.tau / sides)) for i in range(sides)]
    for x, z in ring:
        positions.extend(((x / 2, -.5, z / 2), (x / 2, .5, z / 2)))
        normals.extend(((x, 0, z), (x, 0, z)))
    for i in range(sides):
        a, b = i * 2, (i + 1) % sides * 2
        indices.extend((a, a + 1, b + 1, a, b + 1, b))
    for sign in (-1, 1):
        center = len(positions)
        positions.append((0, sign / 2, 0))
        positions.extend((x / 2, sign / 2, z / 2) for x, z in ring)
        normals.extend([(0, sign, 0)] * (sides + 1))
        for i in range(sides):
            a, b = center + 1 + i, center + 1 + (i + 1) % sides
            indices.extend((center, b, a) if sign > 0 else (center, a, b))
    return positions, normals, indices


GEOMETRIES = {"box": box_geometry, "sphere": sphere_geometry, "cylinder": cylinder_geometry}
AXLE = (1, 0, 0)


class Asset:
    def __init__(self, name, reference):
        self.name = name
        self.data = {
            "asset": {"version": "2.0", "generator": "Marswalk route model builder",
                      "extras": {"reference": reference}},
            "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [], "meshes": [], "materials": [],
            "bufferViews": [], "accessors": [],
        }
        self.buffer = bytearray()
        self.geometry = {}
        self.meshes = {}
        self.materials = {}
        self.channels = []
        self.samplers = []
        self.node(name)

    def accessor(self, values, dtype, component, shape, target=None, bounds=False):
        array = np.asarray(values, dtype=dtype)
        self.buffer.extend(b"\0" * (-len(self.buffer) % 4))
        view = {"buffer": 0, "byteOffset": len(self.buffer), "byteLength": array.nbytes}
        if target is not None:
            view["target"] = target
        self.buffer.extend(array.tobytes())
        self.data["bufferViews"].append(view)
        accessor = {"bufferView": len(self.data["bufferViews"]) - 1, "componentType": component,
                    "count": len(array), "type": shape}
        if bounds:
            limits = array.reshape(len(array), -1)
            accessor.update(min=limits.min(axis=0).tolist(), max=limits.max(axis=0).tolist())
        self.data["accessors"].append(accessor)
        return len(self.data["accessors"]) - 1

    def mesh(self, shape, color):
        key = (shape, color)
        if key not in self.meshes:
            if shape not in self.geometry:
                positions, normals, indices = GEOMETRIES[shape]()
                self.geometry[shape] = {
                    "attributes": {
                        "POSITION": self.accessor(positions, "<f4", 5126, "VEC3", 34962, bounds=True),
                        "NORMAL": self.accessor(normals, "<f4", 5126, "VEC3", 34962),
                    },
                    "indices": self.accessor(indices, "<u2", 5123, "SCALAR", 34963),
                }
            if color not in self.materials:
                rgb = [int(COLORS[color][i:i + 2], 16) / 255 for i in (0, 2, 4)]
                linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
                self.materials[color] = len(self.data["materials"])
                self.data["materials"].append({"name": color, "pbrMetallicRoughness": {
                    "baseColorFactor": linear + [1], "metallicFactor": 0, "roughnessFactor": .72,
                }})
            primitive = {**self.geometry[shape], "material": self.materials[color]}
            self.meshes[key] = len(self.data["meshes"])
            self.data["meshes"].append({"primitives": [primitive]})
        return self.meshes[key]

    def node(self, name, center=(0, 0, 0), parent=None, **props):
        nodes = self.data["nodes"]
        index = len(nodes)
        nodes.append({"name": name, "translation": center, **props})
        if parent is not None:
            nodes[parent].setdefault("children", []).append(index)
        return index

    def part(self, name, shape, color, center, size, parent=0, angle=0, axis=AXLE):
        return self.node(name, center, parent, mesh=self.mesh(shape, color), scale=size,
                         rotation=rotation(axis, angle))

    def animate(self, node, path, times, values):
        sampler = {"input": self.accessor(times, "<f4", 5126, "SCALAR", bounds=True),
                   "output": self.accessor(values, "<f4", 5126, "VEC4" if path == "rotation" else "VEC3"),
                   "interpolation": "LINEAR"}
        self.channels.append({"sampler": len(self.samplers), "target": {"node": node, "path": path}})
        self.samplers.append(sampler)

    def export(self):
        self.buffer.extend(b"\0" * (-len(self.buffer) % 4))
        self.data["buffers"] = [{"byteLength": len(self.buffer)}]
        self.data["animations"] = [{"name": "Traverse", "channels": self.channels, "samplers": self.samplers}]
        metadata = json.dumps(self.data, separators=(",", ":")).encode()
        metadata += b" " * (-len(metadata) % 4)
        with (DEST / f"{self.name}.glb").open("wb") as target:
            target.write(struct.pack("<4sII", b"glTF", 2, 28 + len(metadata) + len(self.buffer)))
            target.write(struct.pack("<I4s", len(metadata), b"JSON"))
            target.write(metadata)
            target.write(struct.pack("<I4s", len(self.buffer), b"BIN\0"))
            target.write(self.buffer)


def astronaut():
    asset = Asset("astronaut", "https://www.nasa.gov/image-article/new-spacesuit-artemis-generation-astronauts/")
    body = asset.part
    body("Pressure garment", "sphere", "white", (0, 1.34, 0), (.62, .67, .42))
    body("Waist bearing", "cylinder", "dark", (0, 1.05, 0), (.43, .14, .37))
    body("Life support backpack", "box", "white", (0, 1.36, -.28), (.5, .62, .24))
    body("Backpack fittings", "box", "blue", (0, 1.44, -.408), (.31, .23, .024))
    body("Helmet shell", "sphere", "white", (0, 1.8, .02), (.43, .43, .43))
    body("Gold sun visor", "sphere", "visor", (0, 1.8, .16), (.36, .29, .24))
    body("Visor highlight", "sphere", "gold", (-.077, 1.868, .244), (.12, .045, .035))
    body("Chest controls", "box", "blue", (0, 1.42, .21), (.25, .16, .06))
    times = [0, .24, .48, .72, .96]
    for side in (-1, 1):
        leg = asset.node("Hip pivot", (side * .155, 1.04, 0), 0)
        body("Suit leg", "sphere", "white", (0, -.39, 0), (.26, .85, .29), leg)
        body("Knee pad", "sphere", "metal", (0, -.43, .11), (.19, .18, .13), leg)
        body("Boot", "sphere", "white", (0, -.92, .07), (.235, .22, .40), leg)
        arm = asset.node("Shoulder pivot", (side * .34, 1.55, 0), 0)
        body("Sleeve", "sphere", "white", (side * .035, -.285, 0), (.215, .63, .22), arm)
        body("Shoulder stripe", "cylinder", "red", (side * .035, -.13, 0), (.218, .07, .218), arm)
        body("Glove", "sphere", "dark", (side * .035, -.63, .04), (.19, .21, .19), arm)
        for pivot, swing in [(leg, side * .32), (arm, side * -.29)]:
            asset.animate(pivot, "rotation", times, [rotation(AXLE, angle) for angle in (0, swing, 0, -swing, 0)])
    asset.animate(0, "translation", times, [(0, rise, 0) for rise in (0, .055, 0, .055, 0)])
    return asset


def wheel(asset, x, z, radius, width, hub, rim="rubber"):
    rotor = asset.node("Wheel axle", (x, radius, z), 0)
    across = math.pi / 2
    asset.part("Wheel", "cylinder", rim, (0, 0, 0), (2 * radius, width, 2 * radius),
               rotor, across, (0, 0, 1))
    for side in (-1, 1):
        asset.part("Wheel hub", "cylinder", hub, (side * width * .53, 0, 0),
                   (1.02 * radius, width * .10, 1.02 * radius), rotor, across, (0, 0, 1))
    for step in range(12):
        a = math.tau * step / 12
        asset.part("Tread", "box", "metal" if rim == "metal" else "dark",
                   (0, radius * math.cos(a), radius * math.sin(a)), (width * .93, .075 * radius, .29 * radius),
                   rotor, a)
    asset.animate(rotor, "rotation", [0, .32, .64, .96, 1.28],
                  [rotation(AXLE, math.tau * i / 4) for i in range(5)])


def panels(asset, xs, y, z, width, length):
    for x in xs:
        asset.part("Solar panel frame", "box", "metal", (x, y, z), (width, .052, length))
        for i in (-1, 0, 1):
            asset.part("Solar cell bank", "box", "solar", (x, y + .029, z + i * length / 3),
                       (width * .94, .014, length * .30))


def mast(asset, x, y, z, height, width, color="white"):
    p = asset.part
    p("Mast", "cylinder", "metal", (x, y + height / 2, z), (.10, height, .10))
    p("Camera bar", "box", color, (x, y + height, z), (width, .19, .22))
    for side in (-1, 1):
        p("Stereo lens", "sphere", "black", (x + width * side * .30, y + height, z + .115),
          (.115, .115, .07))


ROBOT_PROFILES = {
    "perseverance": (1.52, 2.35, .26, "white", "metal",
                     "https://science.nasa.gov/mission/mars-2020-perseverance/rover-components/"),
    "small_rover": (1.44, 2.33, .25, "cream", "dark",
                    "https://science.nasa.gov/wp-content/uploads/2024/03/44706_MSLCuriosityBrochure.pdf"),
    "sojourner": (.42, .62, .065, "metal", "black", "https://science.nasa.gov/photojournal/rovers-and-sojourner/"),
    "mer": (.91, 1.29, .13, "foil", "metal", "https://science.nasa.gov/mission/mer-spirit/"),
    "zhurong": (1.19, 2.02, .17, "gold", "metal",
                "https://www.cnsa.gov.cn/english/n6465652/n6465653/c6840321/content.html"),
    "rosalind_franklin": (1.14, 1.81, .15, "white", "metal",
                         "https://explorationscience.esa.int/project/exomars-rosalind-franklin-rfm/"),
}


def robot(name, width, length, r, color, hub, url):
    asset = Asset(name, url)
    p = asset.part
    h = r * 2.0
    for x in (-width * .64, width * .64):
        for z in (-length * .46, -.03 * length, length * .45):
            wheel(asset, x, z, r, r * .76, hub)
        p("Rocker bogie", "box", "metal", (x * .83, h * .74, 0), (r * .35, r * .42, length * .84))
    p("Equipment deck", "box", color, (0, h, 0), (width, r * 1.45, length))
    p("Lower chassis", "box", "dark", (0, h - r * .65, -.04 * length),
      (.78 * width, .50 * r, .84 * length))
    if name in ("perseverance", "small_rover"):
        top = h + r * .7
        p("MMRTG", "cylinder", "metal", (.05, top + .10, -.46 * length), (.39, .68, .39), angle=math.pi / 2)
        for fin in range(5):
            p("Radiator fin", "box", "white", (.05, top + .10, -.46 * length + fin * .075), (.51, .42, .025))
        p("Robotic arm", "box", "metal", (.30 * width, h - .11, .58 * length), (.16, .19, .79), angle=.28)
        p("Tool turret", "cylinder", "dark", (.30 * width, h + .02, .76 * length), (.30, .23, .30))
        mast(asset, -width * .34, top, length * .34, 1.12 if name == "perseverance" else 1.22,
             .45 if name == "perseverance" else .34, "white" if name == "perseverance" else "metal")
        p("High gain antenna", "sphere", "white", (.38, top + .19, -.26), (.42, .13, .42))
        if name == "perseverance":
            p("Sample caching cover", "box", "white", (-.24, top + .08, .30), (.49, .20, .50))
        else:
            p("Instrument enclosure", "box", "foil", (.19, top + .12, .21), (.52, .24, .62))
    elif name == "sojourner":
        panels(asset, [0], h + r * .90, 0, width * .98, length * .84)
        p("Forward camera and bumper", "box", "dark", (0, h, length * .52), (.24, .07, .075))
        p("Antenna", "cylinder", "metal", (.13, h + .15, -.21), (.015, .24, .015))
    else:
        top = h + r * .8
        wing = width * (.72 if name == "zhurong" else .58)
        panels(asset, [-wing, 0, wing], top, -.10 * length, width * .58, length * .73)
        mast(asset, -width * .22, top, length * .36, .76 if name == "mer" else .96, .37)
        if name == "mer":
            p("Dish antenna", "sphere", "white", (width * .28, top + .21, .08), (.39, .12, .39))
        if name == "zhurong":
            panels(asset, [0], top, -.57 * length, width * .91, length * .39)
            p("Front obstacle sensor", "box", "gold", (0, h, length * .54), (.41, .16, .16))
        if name == "rosalind_franklin":
            p("Drill enclosure", "box", "metal", (.13, h + .03, length * .55), (.59, .48, .33))
            p("Drill shaft", "cylinder", "dark", (.13, h -.19, length * .61), (.09, .43, .09))
    return asset


OPEN_REF = "https://science.nasa.gov/resource/apollo-17-gene-cernan-in-lunar-roving-vehicle/"
SEV_REF = "https://science.nasa.gov/3d-resources/space-exploration-vehicle/"
BIKE_REF = "https://ntrs.nasa.gov/api/citations/20200002475/downloads/20200002475.pdf"


def crew(name, kind):
    asset = Asset(name, {"open": OPEN_REF, "cabin": SEV_REF, "bike": BIKE_REF}[kind])
    p = asset.part
    if kind == "bike":
        for z in (-.79, .79):
            wheel(asset, 0, z, .32, .18, "metal")
        p("Frame", "box", "orange", (0, .54, 0), (.32, .33, 1.19))
        p("Seat", "box", "dark", (0, .83, -.27), (.30, .12, .56))
        p("Handlebar", "cylinder", "metal", (0, 1.05, .53), (.08, .74, .08), angle=math.pi / 2, axis=(0, 0, 1))
        p("Front fork", "cylinder", "metal", (0, .65, .64), (.09, .80, .09), angle=.33)
        p("Rider suit", "sphere", "white", (0, 1.10, -.11), (.44, .62, .38), angle=.34)
        p("Rider helmet", "sphere", "white", (0, 1.49, .07), (.35, .35, .35))
        p("Rider visor", "sphere", "visor", (0, 1.49, .20), (.29, .23, .15))
    elif kind == "open":
        color = "cream" if name == "unpressurized_rover" else "orange"
        for x in (-.83, .83):
            for z in (-1.00, 1.00):
                wheel(asset, x, z, .37, .22, "metal", "metal")
                p("Fender", "box", color, (x, .85, z), (.32, .11, .65))
        p("Open chassis", "box", color, (0, .57, 0), (1.37, .24, 2.46))
        for x in (-.36, .36):
            p("Seat cushion", "box", "dark", (x, .76, -.28), (.48, .14, .53))
            p("Seat back", "box", "dark", (x, .98, -.52), (.48, .52, .12), angle=.12)
        p("Control panel", "box", "metal", (0, .90, .33), (.45, .34, .30))
        p("Antenna mast", "cylinder", "metal", (.47, 1.16, .84), (.055, 1.14, .055))
        p("Dish antenna", "sphere", "gold", (.47, 1.73, .84), (.61, .14, .61))
        if name == "four_wheel":
            p("Tool rack", "box", "metal", (0, .77, -1.06), (1.27, .20, .40))
            p("Rack case", "box", "orange", (0, .99, -1.06), (.86, .23, .37))
            for x in (-.65, .65):
                p("Roll hoop post", "cylinder", "dark", (x, 1.16, -.63), (.065, .91, .065))
            p("Roll hoop crossbar", "box", "dark", (0, 1.61, -.63), (1.35, .07, .07))
    else:
        width = 2.18 if name == "pressurized_rover" else 1.75
        color = "white" if name == "pressurized_rover" else "cream"
        for x in (-width * .59, width * .59):
            for z in (-1.32, 0, 1.32):
                wheel(asset, x, z, .46, .31, "metal")
        p("Wheel platform", "box", "metal", (0, .72, 0), (width, .30, 3.5))
        p("Pressure cabin", "sphere", color, (0, 1.52, .10), (width, 1.88, 3.55))
        p("Cabin lower skirt", "box", color, (0, 1.02, .08), (width * .91, .46, 2.75))
        p("Panoramic windshield", "sphere", "glass", (0, 1.83, 1.59), (width * .81, .68, .78))
        p("Windshield mullion", "box", "white", (0, 1.84, 1.97), (.073, .43, .054))
        for x in (-width * .43, width * .43):
            p("Side glazing", "sphere", "glass", (x, 1.79, .55), (.30, .49, .99))
        p("Rear airlock", "cylinder", "metal", (0, 1.48, -1.48), (.78, .40, .78), angle=math.pi / 2)
        p("Roof communications", "sphere", "white", (.27, 2.50, -.47), (.43, .29, .43))
        if name == "buggy":
            p("Equipment rack", "box", "orange", (0, .97, -1.65), (width * .82, .26, .42))
    return asset


if __name__ == "__main__":
    DEST.mkdir(exist_ok=True)
    models = [astronaut()]
    models.extend(robot(name, *profile) for name, profile in ROBOT_PROFILES.items())
    models.extend(crew(name, kind) for name, kind in [
        ("two_wheel", "bike"), ("unpressurized_rover", "open"), ("four_wheel", "open"),
        ("pressurized_rover", "cabin"), ("buggy", "cabin"),
    ])
    for model in models:
        model.export()
