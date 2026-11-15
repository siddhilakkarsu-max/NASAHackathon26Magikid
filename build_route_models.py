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
    # High-poly route assets: the smooth parts (camera lenses, bearing caps,
    # hose fittings and suit hardware) stay round when the camera is close.
    # This is deliberately still procedural and compact rather than embedding
    # the much larger source CAD meshes.
    slices, rings = 48, 32
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
    sides = 48
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


class Facets:
    """Small flat-shaded meshes for mechanical parts."""

    def __init__(self):
        self.positions, self.normals, self.indices = [], [], []

    def face(self, vertices):
        vertices = np.asarray(vertices)
        normal = np.cross(vertices[1] - vertices[0], vertices[2] - vertices[0])
        normal /= np.linalg.norm(normal)
        offset = len(self.positions)
        self.positions.extend(vertices)
        self.normals.extend([normal] * len(vertices))
        for i in range(1, len(vertices) - 1):
            self.indices.extend((offset, offset + i, offset + i + 1))

    def geometry(self):
        return self.positions, self.normals, self.indices


def beveled_box_geometry():
    outline = [(-.39, -.5), (.39, -.5), (.5, -.39), (.5, .39),
               (.39, .5), (-.39, .5), (-.5, .39), (-.5, -.39)]
    levels = [[(x * scale, y, z * scale) for x, z in outline]
              for y, scale in [(-.5, .83), (-.36, 1), (.36, 1), (.5, .83)]]
    facets = Facets()
    for lower, upper in zip(levels, levels[1:]):
        for i in range(len(outline)):
            j = (i + 1) % len(outline)
            facets.face([lower[i], upper[i], upper[j], lower[j]])
    facets.face(levels[0])
    facets.face(levels[-1][::-1])
    return facets.geometry()


def rover_tire_geometry(chevron=False):
    facets = Facets()
    # The NASA rover pages call out curved aluminum wheels and many traction
    # grousers.  A 64-segment tire keeps the curved sidewall smooth while the
    # separate grouser meshes preserve the mechanical silhouette.
    segments = 64
    def ring(radius, y):
        return [(radius * math.cos(a), y, radius * math.sin(a))
                for a in (i * math.tau / segments for i in range(segments))]
    rings = [ring(radius, y) for radius, y in (
        (.39, -.5), (.475, -.5), (.5, -.41), (.5, .41), (.475, .5), (.39, .5))]
    for current, next_ring in zip(rings, rings[1:] + rings[:1]):
        for i in range(segments):
            j = (i + 1) % segments
            facets.face([current[i], next_ring[i], next_ring[j], current[j]])
    for step in range(segments):
        theta = step * math.tau / segments
        def point(y, angle, radius):
            return radius * math.cos(angle), y, radius * math.sin(angle)
        for low, high in ((-.47, 0), (0, .47)):
            angles = [theta + (.085 * (1 - 2 * abs(y)) if chevron else 0) for y in (low, high)]
            a, b, c, d = (point(y, angle + flank, .523)
                         for y, angle, flank in ((low, angles[0], -.034), (high, angles[1], -.034),
                                                  (high, angles[1], .034), (low, angles[0], .034)))
            facets.face([a, b, c, d])
    return facets.geometry()


GEOMETRIES = {
    "box": box_geometry, "sphere": sphere_geometry, "cylinder": cylinder_geometry,
    "beveled_box": beveled_box_geometry, "straight_tire": rover_tire_geometry,
    "chevron_tire": lambda: rover_tire_geometry(chevron=True),
}
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
                # Use restrained, physically legible responses so the small route
                # models keep their silhouette while metal, glass, visor, and
                # solar surfaces separate cleanly under Cesium lighting.
                surface_response = {
                    "metal": (.78, .36), "foil": (.62, .30), "solar": (.28, .40),
                    "glass": (.12, .18), "visor": (.60, .22), "gold": (.54, .28),
                    "rubber": (.02, .86), "black": (.04, .82), "dark": (.10, .70),
                }
                metallic, roughness = surface_response.get(color, (0, .72))
                material = {"name": color, "pbrMetallicRoughness": {
                    "baseColorFactor": linear + [1], "metallicFactor": metallic,
                    "roughnessFactor": roughness,
                }}
                if color == "solar":
                    material["emissiveFactor"] = [linear[0] * .025, linear[1] * .025, linear[2] * .04]
                elif color in ("glass", "visor"):
                    material["alphaMode"] = "OPAQUE"
                self.data["materials"].append(material)
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
    carrier = asset.node("Pressure suit", (0, 0, 0), 0)
    body("Hard upper torso", "sphere", "white", (0, 1.39, 0), (.65, .58, .48), carrier)
    body("Waist garment", "sphere", "white", (0, 1.10, 0), (.50, .30, .42), carrier)
    for y in (1.12, 1.15, 1.18):
        body("Waist pleat", "cylinder", "metal", (0, y, 0), (.48, .012, .43), carrier)
    body("Life support backpack", "box", "white", (0, 1.45, -.32), (.52, .68, .28), carrier)
    body("Backpack padded cover", "sphere", "white", (0, 1.47, -.420), (.56, .75, .18), carrier)
    body("Backpack vent frame", "box", "metal", (0, 1.48, -.508), (.31, .25, .031), carrier)
    for y in (1.39, 1.43, 1.47, 1.51, 1.55):
        body("Backpack vent slat", "box", "dark", (0, y, -.527), (.23, .014, .014), carrier)
    body("Helmet bearing seal", "cylinder", "dark", (0, 1.64, .025), (.40, .080, .38), carrier)
    body("Helmet shell", "sphere", "white", (0, 1.81, .025), (.44, .41, .41), carrier)
    body("Visor outer gasket", "sphere", "dark", (0, 1.80, .126), (.392, .32, .263), carrier)
    body("Gold sun visor", "sphere", "gold", (0, 1.802, .149), (.363, .290, .243), carrier)
    body("Visor reflected glint", "sphere", "cream", (-.068, 1.875, .243), (.091, .018, .009), carrier)
    for side in (-1, 1):
        body("Helmet light housing", "box", "white", (side * .18, 1.865, .169), (.09, .09, .12), carrier)
        body("Helmet lamp", "sphere", "cream", (side * .18, 1.864, .233), (.053, .043, .02), carrier)
    body("Chest controls", "box", "white", (0, 1.387, .232), (.27, .185, .086), carrier)
    body("Control panel face", "box", "metal", (0, 1.402, .281), (.222, .134, .018), carrier)
    body("Status display", "box", "dark", (-.043, 1.429, .294), (.107, .046, .014), carrier)
    for x in (-.064, -.019, .026, .07):
        body("Chest toggle", "box", "white", (x, 1.373, .296), (.021, .026, .018), carrier)
    body("Torso identification tab", "box", "red", (.16, 1.521, .21), (.079, .036, .017), carrier)
    body("Torso patch", "box", "blue", (-.16, 1.521, .21), (.071, .044, .017), carrier)
    visor = asset.data["materials"][asset.materials["gold"]]["pbrMetallicRoughness"]
    visor.update(metallicFactor=.62, roughnessFactor=.28)
    times = [0, .24, .48, .72, .96]
    for side in (-1, 1):
        limb = "Left" if side < 0 else "Right"
        hip = asset.node(f"{limb} hip bearing", (side * .152, 1.035, 0), carrier)
        body("Thigh garment", "sphere", "white", (0, -.239, 0), (.277, .57, .31), hip)
        body("Thigh pocket", "box", "white", (side * .099, -.24, .09), (.118, .147, .13), hip)
        knee = asset.node(f"{limb} knee bearing", (0, -.49, 0), hip)
        for y in (-.02, .013, .046):
            body("Knee flex ring", "cylinder", "metal", (0, y, 0), (.225, .020, .25), knee)
        body("Knee guard", "sphere", "white", (0, 0, .104), (.204, .19, .109), knee)
        body("Shin garment", "sphere", "white", (0, -.20, 0), (.222, .448, .236), knee)
        body("Ankle cuff", "cylinder", "blue", (0, -.376, .006), (.223, .040, .245), knee)
        foot = asset.node(f"{limb} ankle bearing", (0, -.422, .02), knee)
        body("Boot upper", "sphere", "white", (0, -.044, .056), (.232, .158, .30), foot)
        body("Boot outsole", "box", "dark", (0, -.100, .061), (.223, .033, .294), foot)
        for z in (-.02, .064, .148):
            body("Boot sole lug", "box", "rubber", (0, -.123, z), (.209, .018, .043), foot)
        shoulder = asset.node(f"{limb} shoulder bearing", (side * .307, 1.558, 0), carrier)
        body("Shoulder joint", "sphere", "white", (side * .038, -.06, 0), (.257, .29, .267), shoulder)
        body("Shoulder color band", "cylinder", "red" if side < 0 else "blue", (side * .053, -.136, 0),
             (.228, .044, .243), shoulder)
        body("Upper sleeve", "sphere", "white", (side * .057, -.20, 0), (.232, .35, .248), shoulder)
        elbow = asset.node(f"{limb} elbow bearing", (side * .068, -.333, 0), shoulder)
        for y in (-.02, .011, .042):
            body("Elbow flex ring", "cylinder", "metal", (0, y, 0), (.196, .017, .200), elbow)
        body("Forearm garment", "sphere", "white", (0, -.145, .01), (.202, .30, .220), elbow)
        body("Glove locking ring", "cylinder", "metal", (0, -.268, .02), (.176, .054, .186), elbow)
        body("Glove", "sphere", "white", (0, -.341, .025), (.152, .155, .159), elbow)
        body("Glove grip", "sphere", "dark", (0, -.374, .053), (.112, .096, .117), elbow)
        for finger in (-.070, 0, .070):
            body("Glove finger segment", "box", "white", (finger, -.395, .035), (.045, .050, .070), elbow)
        # The shoulder node already carries the world-space bearing height;
        # keep this ring in the shoulder's local frame so the fasteners sit on
        # the joint instead of duplicating the torso translation and floating
        # above the helmet.
        detail_bolt_ring(asset, (side * .068, 0, 0), .085, count=8, bolt=.018,
                         color="metal", parent=shoulder, name="Shoulder fastener")
        hips = (-.10, -.33, .08, .29, -.10)
        knees = (.10, .42, .16, .06, .10)
        ankles = (0, -.14, -.06, .03, 0)
        if side == 1:
            hips = hips[2:4] + hips[0:3]
            knees = knees[2:4] + knees[0:3]
            ankles = ankles[2:4] + ankles[0:3]
        asset.animate(hip, "rotation", times, [rotation(AXLE, angle) for angle in hips])
        asset.animate(knee, "rotation", times, [rotation(AXLE, angle) for angle in knees])
        asset.animate(foot, "rotation", times, [rotation(AXLE, angle) for angle in ankles])
        asset.animate(shoulder, "rotation", times, [rotation(AXLE, -angle * .74) for angle in hips])
        asset.animate(elbow, "rotation", times, [rotation(AXLE, -.22 + angle * .14) for angle in hips])
    for y in (1.22, 1.29, 1.36):
        body("Torso fabric seam", "cylinder", "metal", (0, y, .246), (.39, .012, .34), carrier)
    for side in (-1, 1):
        rover_strut(asset, "Life support hose", (side * .24, 1.49, -.31),
                    (side * .34, 1.08, -.30), .035, "dark", carrier)
        body("Hip bearing cap", "cylinder", "metal", (side * .152, 1.035, .02), (.20, .060, .20), carrier)
    asset.animate(carrier, "translation", times, [(0, rise, 0) for rise in (.023, .006, .023, .006, .023)])
    return asset


def wheel(asset, x, z, radius, width, hub, rim="rubber"):
    rotor = asset.node("Wheel axle", (x, radius, z), 0)
    across = math.pi / 2
    asset.part("Wheel", "cylinder", rim, (0, 0, 0), (2 * radius, width, 2 * radius),
               rotor, across, (0, 0, 1))
    for side in (-1, 1):
        asset.part("Wheel hub", "cylinder", hub, (side * width * .53, 0, 0),
                   (1.02 * radius, width * .10, 1.02 * radius), rotor, across, (0, 0, 1))
    for step in range(20):
        a = math.tau * step / 20
        asset.part("Tread", "box", "metal" if rim == "metal" else "dark",
                   (0, radius * math.cos(a), radius * math.sin(a)), (width * .93, .075 * radius, .29 * radius),
                   rotor, a)
    for side in (-1, 1):
        detail_bolt_ring(asset, (side * width * .54, 0, 0), radius * .34, count=8, bolt=radius * .055,
                         color="metal" if rim == "metal" else "dark", parent=rotor, name="Hub bolt")
    asset.animate(rotor, "rotation", [0, .32, .64, .96, 1.28],
                  [rotation(AXLE, math.tau * i / 4) for i in range(5)])
    return rotor


def mast(asset, x, y, z, height, width, color="white"):
    p = asset.part
    p("Mast", "cylinder", "metal", (x, y + height / 2, z), (.10, height, .10))
    p("Camera bar", "box", color, (x, y + height, z), (width, .19, .22))
    for side in (-1, 1):
        p("Stereo lens", "sphere", "black", (x + width * side * .30, y + height, z + .115),
          (.115, .115, .07))


def rover_strut(asset, name, start, end, diameter, color, parent=0):
    a = np.asarray(start, dtype=float)
    b = np.asarray(end, dtype=float)
    offset = b - a
    length = np.linalg.norm(offset)
    axis = np.cross((0, 1, 0), offset)
    rotation_axis = AXLE if np.linalg.norm(axis) < 1e-9 else axis / np.linalg.norm(axis)
    angle = math.acos(np.clip(offset[1] / length, -1, 1))
    return asset.part(name, "cylinder", color, ((a + b) / 2).tolist(),
                      (diameter, length, diameter), parent, angle, rotation_axis)


def rover_flange(asset, name, center, diameter, depth, color, parent=0):
    return asset.part(name, "cylinder", color, center, (diameter, depth, diameter),
                      parent, math.pi / 2, (0, 0, 1))


def detail_bolt_ring(asset, center, radius, count=8, bolt=.035, color="metal", parent=0, name="Detail fastener"):
    """Add a compact ring of visible fasteners around a mechanical joint."""
    p = asset.part
    x0, y0, z0 = center
    for step in range(count):
        angle = math.tau * step / count
        p(name, "sphere", color,
          (x0, y0 + radius * math.cos(angle), z0 + radius * math.sin(angle)),
          (bolt, bolt, bolt), parent)


def detail_panel_grid(asset, center, width, height, rows, cols, color="dark", parent=0, name="Panel seam"):
    """Lay narrow seams across a panel so close views read as manufactured hardware."""
    p = asset.part
    x0, y0, z0 = center
    for row in range(1, rows):
        z = z0 - height / 2 + height * row / rows
        p(name, "box", color, (x0, y0, z), (width, .012, .010), parent)
    for col in range(1, cols):
        x = x0 - width / 2 + width * col / cols
        p(name, "box", color, (x, y0, z0), (.010, .012, height), parent)


def science_wheel(asset, x, z, radius, width, chevron=False, small=False):
    p = asset.part
    rotor = asset.node("Wheel axle", (x, radius, z), 0)
    tire = "chevron_tire" if chevron else "straight_tire"
    p("Hollow aluminum tire", tire, "foil" if small else "dark", (0, 0, 0),
      (2 * radius, width, 2 * radius), rotor, math.pi / 2, (0, 0, 1))
    rover_flange(asset, "Drive hub", (0, 0, 0), .61 * radius, width * .95, "metal", rotor)
    for side in (-1, 1):
        flange_x = side * width * .48
        rover_flange(asset, "Hub cap", (flange_x, 0, 0), .39 * radius, width * .14, "dark", rotor)
        for step in range(5 if not chevron else 6):
            a = step * math.tau / (6 if chevron else 5)
            curve = a + (.31 if chevron else .16)
            rover_strut(asset, "Flexure spoke",
                        (flange_x * .80, radius * .26 * math.cos(a), radius * .26 * math.sin(a)),
                        (flange_x, radius * .82 * math.cos(curve), radius * .82 * math.sin(curve)),
                        radius * .104, "metal", rotor)
        detail_bolt_ring(asset, (flange_x, 0, 0), radius * .27, count=8, bolt=radius * .045,
                         color="gold" if chevron else "metal", parent=rotor, name="Suspension hub bolt")
    asset.animate(rotor, "rotation", [0, .32, .64, .96, 1.28],
                  [rotation(AXLE, math.tau * i / 4) for i in range(5)])


def science_suspension(asset, half_track, radius, wheel_z, width, compact=False, chevron=False):
    p = asset.part
    rear, middle, front = wheel_z
    for side in (-1, 1):
        x = side * half_track
        housing_x = x - side * width * .72
        shoulder = (housing_x - side * .08, radius * (2.24 if compact else 2.65), .06)
        rocker = (housing_x, radius * 1.86, rear * .47)
        stubs = [(housing_x, radius * 1.56, z) for z in wheel_z]
        for z, stub in zip(wheel_z, stubs):
            science_wheel(asset, x, z, radius, width, chevron=chevron, small=compact)
            rover_strut(asset, "Steering knuckle", (housing_x, radius, z), stub, radius * .36, "metal")
            rover_flange(asset, "Steering motor", (housing_x, radius, z), radius * .6,
                         width * .76, "metal")
        for start, end in [(shoulder, stubs[2]), (shoulder, rocker), (rocker, stubs[0]), (rocker, stubs[1])]:
            rover_strut(asset, "Rocker bogie link", start, end, radius * .36, "metal" if compact else "dark")
        for x0, y0, z0 in (shoulder, rocker):
            rover_flange(asset, "Bogie pivot", (x0, y0, z0), radius * .68, radius * .35, "metal")
        p("Cross-axle bearing", "beveled_box", "dark", shoulder, (radius * .42, radius * .55, radius * .72))


def msl_rover(name, reference):
    is_msl = name == "small_rover"
    asset = Asset(name, reference)
    p = asset.part
    deck_color = "cream" if is_msl else "white"
    science_suspension(asset, 1.22, .249 if is_msl else .263, (-1.22, -.40, 1.12),
                       .40 if is_msl else .32, chevron=is_msl)
    p("Equipment tub", "beveled_box", deck_color, (0, .89, -.10), (1.72, .55, 2.28))
    p("Wheelwell belly", "beveled_box", "dark", (0, .59, -.11), (1.36, .16, 1.70))
    p("Front science bay", "beveled_box", deck_color, (-.09, .87, 1.03), (1.54, .49, .41))
    p("Deck top", "beveled_box", "metal", (.01, 1.166, -.06), (1.60, .061, 2.12))
    for side in (-1, 1):
        for z in (-.68, .0, .57):
            p("Fastened access panel", "beveled_box", deck_color, (side * .867, .92, z), (.07, .31, .49))
            for dz in (-.17, .17):
                p("Access panel fastener", "sphere", "metal", (side * .913, .99, z + dz), (.036, .037, .037))
        p("Gold service patch", "box", "foil", (side * .887, .760, -.81), (.022, .09, .47))
    p("Fore HAZCAM housing", "beveled_box", "dark", (-.38, .91, 1.26), (.40, .16, .13))
    p("Fore HAZCAM mounting bar", "box", "metal", (-.38, .80, 1.25), (.51, .06, .14))
    for x in (-.49, -.28):
        p("Dark fore sensor lens", "sphere", "black", (x, .917, 1.322), (.103, .102, .066))
    # The rear heat exchanger is angled rather than lying flat across the rear deck.
    p("RTG support", "beveled_box", "metal", (0, 1.15, -.94), (.91, .45, .45), angle=.48)
    p("MMRTG barrel", "cylinder", "foil" if is_msl else "metal", (0, 1.34, -1.18), (.45, .84, .45), angle=-1.02)
    for end in (-1, 1):
        for index in range(5):
            y = 1.13 + .105 * index
            z = -1.35 + .077 * index
            p("Angled MMRTG fin", "beveled_box", deck_color, (end * .22, y, z), (.40, .075, .48), angle=-.49)
    p("Deck equipment housing", "beveled_box", "foil" if is_msl else deck_color,
      (.27, 1.275, -.36), (.52, .21, .52))
    rover_strut(asset, "Antenna post", (.35, 1.17, .45), (.35, 1.40, .45), .075, "metal")
    p("High-gain polygon", "beveled_box", "gold" if is_msl else "white", (.35, 1.47, .45),
      (.46, .065, .42), angle=.35)
    for x, z in ((-.55, -.59), (.51, .71)):
        p("Deck electronics pod", "beveled_box", "metal", (x, 1.26, z), (.22, .19, .28))
    x, z = -.49, .58
    rover_strut(asset, "Remote sensing mast", (x, 1.19, z), (x, 2.24, z), .17, "cream" if is_msl else "white")
    p("Mast azimuth collar", "cylinder", "dark", (x, 1.31, z), (.25, .16, .25))
    p("Mast swivel", "cylinder", "metal", (x, 2.16, z), (.24, .16, .24))
    if is_msl:
        p("ChemCam housing", "beveled_box", "cream", (x, 2.37, z), (.33, .33, .31))
        p("ChemCam black aperture", "sphere", "black", (x, 2.38, z + .155), (.195, .196, .079))
        p("Mastcam dark stereo bar", "beveled_box", "dark", (x, 2.178, z + .064), (.48, .107, .15))
        for offset in (-.163, .16):
            p("Mastcam optics", "sphere", "black", (x + offset, 2.178, z + .15), (.092, .091, .058))
    else:
        p("Mastcam-Z camera head", "beveled_box", "white", (x, 2.27, z), (.52, .22, .28))
        for offset, diameter in ((-.17, .128), (.17, .145)):
            p("Mastcam-Z adjustable optics", "sphere", "black", (x + offset, 2.278, z + .141),
              (diameter, diameter, .09))
        p("SuperCam housing", "beveled_box", "white", (x - .04, 2.47, z - .043), (.285, .25, .25))
        p("SuperCam black aperture", "sphere", "dark", (x - .04, 2.47, z + .078), (.142, .142, .095))
    start = (.51, .87, 1.14)
    elbow = (1.03, .74, 1.78) if is_msl else (.77, .71, 1.41)
    cuff = (1.05, 1.34, 2.18) if is_msl else (-.01, .88, 1.63)
    rover_strut(asset, "Robotics upper boom", start, elbow, .175, "dark" if is_msl else "metal")
    rover_strut(asset, "Robotics forearm", elbow, cuff, .144, "metal")
    for joint in (start, elbow):
        rover_flange(asset, "Robot arm motor joint", joint, .26, .19, "dark")
    p("Multi-instrument drill turret", "beveled_box", "dark" if is_msl else "metal",
      cuff, (.49, .23, .43) if is_msl else (.29, .26, .31), angle=-.21 if is_msl else -.34)
    p("Drill barrel", "cylinder", "dark", (cuff[0], cuff[1], cuff[2] + .18),
      (.084, .24, .084), angle=math.pi / 2)
    if is_msl:
        p("Raised MAHLI instrument", "cylinder", "metal", (cuff[0] - .16, cuff[1] + .105, cuff[2] + .07),
          (.145, .19, .145), angle=math.pi / 2)
    # High-poly close-up pass: deck seams, fasteners, lens bezels, and a visible
    # arm cable make the two MSL silhouettes read as engineered vehicles.
    detail_panel_grid(asset, (0, 1.201, -.06), 1.46, 1.93, 5, 4, "dark", name="Deck panel seam")
    for px, pz in ((-.67, -.76), (.67, -.76), (-.67, .64), (.67, .64)):
        p("Deck corner fastener", "sphere", "gold" if is_msl else "metal", (px, 1.225, pz), (.042, .026, .042))
    detail_bolt_ring(asset, start, .105, count=8, bolt=.032, color="gold" if is_msl else "metal",
                     name="Robot arm joint fastener")
    detail_bolt_ring(asset, elbow, .105, count=8, bolt=.030, color="dark",
                     name="Robot elbow fastener")
    rover_strut(asset, "Arm service cable", (start[0] + .06, start[1] + .10, start[2] + .08),
                (elbow[0] + .04, elbow[1] + .08, elbow[2] + .04), .024, "gold")
    p("Front sensor bezel", "cylinder", "dark", (-.38, .93, 1.335), (.235, .035, .235), angle=math.pi / 2)
    if not is_msl:
        # Perseverance's reference silhouette carries visible avionics boxes and
        # bundled camera wiring around the mast and deck.
        p("Front avionics module", "beveled_box", "white", (-.60, 1.30, .68), (.38, .24, .44))
        p("Rear avionics module", "beveled_box", "foil", (.58, 1.31, -.64), (.42, .25, .48))
        p("Navigation electronics canister", "cylinder", "metal", (.37, 1.38, .72), (.16, .24, .16))
        detail_bolt_ring(asset, (-.60, 1.42, .68), .10, count=8, bolt=.024, color="metal",
                         name="Front module fastener")
        detail_bolt_ring(asset, (.58, 1.43, -.64), .11, count=8, bolt=.024, color="gold",
                         name="Rear module fastener")
        for side in (-1, 1):
            rover_strut(asset, "Mast camera data wire", (x + side * .15, 2.16, z + .13),
                        (x + side * .15, 1.37, z + .13), .018, "gold")
            rover_strut(asset, "Mast service wire", (x + side * .23, 2.19, z + .04),
                        (x + side * .31, 1.72, z + .04), .014, "dark")
        rover_strut(asset, "Deck harness bundle", (.54, 1.35, -.50), (.55, 1.30, .62), .025, "gold")
    return asset


def mer_rover(reference):
    asset = Asset("mer", reference)
    p = asset.part
    science_suspension(asset, .62, .128, (-.59, -.12, .59), .164, compact=True)
    p("Gold warm electronics body", "beveled_box", "foil", (0, .382, -.03), (.91, .31, 1.06))
    p("Lower mobility frame", "beveled_box", "metal", (0, .227, -.04), (.71, .08, .91))
    for x in (-.18, .18):
        p("Pancam under-deck hazard optics", "sphere", "dark", (x, .394, .523), (.13, .12, .084))
    # Spirit and Opportunity's swept side arrays are four separate shaded leaves.
    for x, z, width, length, turn in [(0, -.015, .93, 1.19, 0), (-.68, -.23, .56, .70, .29),
                                     (.68, -.23, .56, .70, -.29), (-.73, .32, .63, .58, -.14),
                                     (.73, .32, .63, .58, .14)]:
        axis = (0, 1, 0)
        p("Swept array gold frame", "beveled_box", "foil", (x, .557, z), (width, .039, length), angle=turn, axis=axis)
        p("Solar array face", "beveled_box", "black", (x, .577, z), (width * .97, .019, length * .97), angle=turn, axis=axis)
        for row in (-.31, -.12, .09, .29):
            dx, dz = math.sin(turn) * row * length, math.cos(turn) * row * length
            p("Dark solar cell band", "box", "solar", (x + dx, .592, z + dz),
              (width * .87, .008, length * .162), angle=turn, axis=axis)
        p("Array hinge", "cylinder", "metal", (x * .68, .606, z), (.064, .034, .064))
    x, z = -.13, .36
    rover_strut(asset, "Cream Pancam mast", (x, .561, z), (x, 1.255, z), .126, "cream")
    p("Pancam pivot", "cylinder", "metal", (x, 1.223, z), (.21, .15, .21))
    p("Wide Pancam lens bank", "beveled_box", "cream", (x, 1.386, z), (.55, .187, .162))
    for offset, size, color in ((-.194, .115, "black"), (-.093, .067, "dark"),
                                (.093, .067, "dark"), (.194, .115, "black")):
        p("Pancam lens", "sphere", color, (x + offset, 1.386, z + .076), (size, size, .074))
    rover_strut(asset, "High-gain dish mount", (.34, .57, -.31), (.42, .86, -.29), .086, "white")
    p("Raised high-gain dish", "sphere", "gold", (.42, .903, -.255), (.34, .080, .32), angle=1.01)
    p("Dish central reflector", "sphere", "foil", (.42, .903, -.213), (.25, .055, .24), angle=1.01)
    rover_strut(asset, "Low gain aerial", (.18, .59, -.27), (.18, 1.30, -.27), .034, "metal")
    rover_strut(asset, "Instrument arm boom", (.36, .36, .43), (.53, .29, .73), .087, "cream")
    rover_strut(asset, "Instrument arm cuff", (.53, .29, .73), (.42, .23, .88), .066, "metal")
    p("Instrument arm end package", "beveled_box", "dark", (.42, .23, .89), (.16, .13, .14))
    for px, pz in ((-.34, -.42), (.34, -.42), (-.34, .42), (.34, .42)):
        p("MER chassis fastener", "sphere", "gold", (px, .565, pz), (.032, .028, .032))
    detail_bolt_ring(asset, (x, 1.22, z), .095, count=10, bolt=.026, color="gold",
                     name="Pancam pivot fastener")
    for step in range(6):
        angle = math.tau * step / 6
        rover_strut(asset, "Dish support spoke", (.42, .903, -.255),
                    (.42 + .22 * math.cos(angle), .903, -.255 + .22 * math.sin(angle)), .018, "metal")
    rover_strut(asset, "Instrument arm service cable", (.36, .42, .46), (.50, .33, .72), .021, "gold")
    return asset


def rover_plate_geometry():
    """A convex panel with clipped corners and flat edges."""
    contour = [(-.37, -.50), (.37, -.50), (.50, -.37), (.50, .37),
               (.37, .50), (-.37, .50), (-.50, .37), (-.50, -.37)]
    positions, normals, indices = [], [], []
    for side in (-1, 1):
        offset = len(positions)
        positions.extend((x, side / 2, z) for x, z in contour)
        normals.extend([(0, side, 0)] * len(contour))
        for i in range(1, len(contour) - 1):
            face = (0, i + 1, i) if side == 1 else (0, i, i + 1)
            indices.extend(offset + j for j in face)
    for i, (x, z) in enumerate(contour):
        x_next, z_next = contour[(i + 1) % len(contour)]
        edge = np.array((z_next - z, 0, x - x_next))
        normal = edge / np.linalg.norm(edge)
        offset = len(positions)
        positions.extend(((x, -.5, z), (x_next, -.5, z_next),
                          (x_next, .5, z_next), (x, .5, z)))
        normals.extend([normal] * 4)
        indices.extend(offset + j for j in (0, 3, 2, 0, 2, 1))
    return positions, normals, indices


def rover_cell_grid_geometry():
    """Represent a solar-cell grid with one draw per panel."""
    positions, indices = [], []
    for x in np.linspace(-.40, .40, 9):
        a = len(positions)
        positions.extend(((x - .003, 0, -.40), (x - .003, 0, .40),
                          (x + .003, 0, .40), (x + .003, 0, -.40)))
        indices.extend((a, a + 1, a + 2, a, a + 2, a + 3))
    for z in np.linspace(-.40, .40, 11):
        a = len(positions)
        positions.extend(((-.40, 0, z - .003), (-.40, 0, z + .003),
                          (.40, 0, z + .003), (.40, 0, z - .003)))
        indices.extend((a, a + 1, a + 2, a, a + 2, a + 3))
    return positions, [(0, 1, 0)] * len(positions), indices


GEOMETRIES.update(rover_plate=rover_plate_geometry, rover_cell_grid=rover_cell_grid_geometry)


def rover_array(asset, name, center, width, length, color="solar", yaw=0):
    panel = asset.node(name, center, 0, rotation=rotation((0, 1, 0), yaw))
    thickness = min(width, length) * .035
    asset.part("Panel backing", "rover_plate", "metal", (0, 0, 0),
               (width, thickness, length), panel)
    asset.part("Photovoltaic glass", "rover_plate", color, (0, thickness * .61, 0),
               (.964 * width, thickness * .28, .964 * length), panel)
    asset.part("Cell grid", "rover_cell_grid", "metal", (0, thickness * .77, 0),
               (width, 1, length), panel)


def light_rover_suspension(asset, width, length, radius, hub, striped=False):
    for side in (-1, 1):
        x = width * .64 * side
        tire_width = radius * .76
        wheel_centers = [(x, radius, length * z) for z in (-.46, -.03, .45)]
        joint = (width * .46 * side, radius * 2.42, -length * .13)
        rocker = (width * .57 * side, radius * 1.55, length * .16)
        for i, (wx, wy, wz) in enumerate(wheel_centers):
            rotor = wheel(asset, wx, wz, radius, tire_width, hub, "metal")
            motor = (wx - side * tire_width * .45, wy + radius * .28, wz)
            rover_strut(asset, "Suspension arm", joint if i == 0 else rocker, motor,
                        radius * .29, "metal")
            asset.part("Steering motor", "cylinder", "dark", motor,
                       (radius * .43, radius * .35, radius * .43))
            asset.part("Drive gearbox", "cylinder", "metal", (motor[0] - side * .035, motor[1], motor[2]),
                       (radius * .34, radius * .08, radius * .34), angle=math.pi / 2, axis=(0, 0, 1))
            for tooth in range(8):
                tooth_angle = math.tau * tooth / 8
                asset.part("Drive gear tooth", "box", "gold",
                           (motor[0] - side * .055,
                            motor[1] + radius * .19 * math.cos(tooth_angle),
                            motor[2] + radius * .19 * math.sin(tooth_angle)),
                           (radius * .12, radius * .045, radius * .07), angle=tooth_angle)
            if striped:
                for step in range(6):
                    angle = step * math.tau / 6
                    asset.part("Radial wheel spoke", "box", "gold",
                               (side * tire_width * .56, .59 * radius * math.cos(angle),
                                .59 * radius * math.sin(angle)),
                               (radius * .16, radius * .53, radius * .13), rotor, angle)
        rover_strut(asset, "Rocker bogie beam", joint, rocker, radius * .34, "metal")
        rover_flange(asset, "Bogie hinge cap", joint, radius * .57, radius * .31, hub)


def sojourner_body(asset, width, length, r, hub):
    p = asset.part
    light_rover_suspension(asset, width, length, r, hub)
    p("Gold foil electronics chassis", "rover_plate", "gold",
      (0, .143, 0), (.90 * width, .115, .93 * length))
    rover_array(asset, "Flat solar canopy", (0, .211, -.01), width * 1.15, length * 1.04, "dark")
    for side in (-1, 1):
        x = width * side * .455
        z = length * .44
        rover_strut(asset, "Foil harness", (x, .13, z), (x, .193, z - .042), .009, "gold")
        rover_strut(asset, "Foil harness", (x, .193, z - .042), (x, .193, -.25), .009, "gold")
        p("Hazard camera", "beveled_box", "dark", (side * .104, .171, .298), (.053, .041, .022))
        p("Camera lens", "sphere", "black", (side * .104, .173, .312), (.019, .019, .010))
    rover_strut(asset, "Front crossbar", (-.177, .085, .309), (.177, .085, .309), .016, "white")
    antenna = (-.16, .214, -.26)
    elbow = (-.16, .307, -.26)
    stem = (-.166, .342, -.277)
    rover_strut(asset, "Antenna stalk", antenna, elbow, .015, "metal")
    rover_strut(asset, "Antenna bend", elbow, stem, .014, "metal")
    rover_strut(asset, "Antenna whip", stem, (-.166, .428, -.277), .010, "metal")
    # Keep the compact panel perimeter from the reference. The earlier pass
    # added long rails and loose spherical clamps that read as floating parts.
    for px, pz in ((-.18, -.28), (.18, -.28), (-.18, .28), (.18, .28)):
        p("Solar canopy fastener", "cylinder", "metal", (px, .224, pz), (.038, .018, .038), angle=math.pi / 2)
    for side, pz in ((-1, -.15), (1, -.15), (-1, .18), (1, .18)):
        p("Sojourner chassis nut", "box", "metal", (side * .34, .171, pz), (.042, .030, .042))


def zhurong_body(asset, width, length, r, hub):
    p = asset.part
    light_rover_suspension(asset, width, length, r, hub, striped=True)
    p("Copper body shell", "rover_plate", "gold", (0, .36, -.03), (width, .31, length * .83))
    p("Upper deck", "rover_plate", "white", (0, .526, -.03), (width * 1.01, .044, length * .85))
    p("Tapered nose", "beveled_box", "metal", (0, .35, length * .43), (.83, .233, .238), angle=-.23)
    p("Front obstacle sensor", "beveled_box", "gold", (0, .421, length * .491), (.41, .12, .13))
    for side in (-1, 1):
        rover_array(asset, "Forward solar petal", (side * .786, .552, .35),
                    .73, .73, "dark", side * math.radians(9))
        rover_array(asset, "Rear solar petal", (side * .794, .552, -.40),
                    .79, .81, "dark", side * math.radians(-8))
        rover_strut(asset, "Solar wing spar", (side * .42, .510, -.34), (side * .88, .528, -.34),
                    .038, "metal")
    p("Mast base", "beveled_box", "foil", (-.31, .596, .54), (.21, .15, .23))
    rover_strut(asset, "Exposed copper mast", (-.31, .647, .54), (-.31, 1.624, .54), .059, "foil")
    # A restrained service lead follows the mast down to the deck; keeping it
    # as a real strut gives the high-poly audit an explicit wire endpoint to
    # inspect instead of leaving a decorative line floating in space.
    rover_strut(asset, "Mast service cable", (-.25, .66, .48), (-.25, 1.47, .48), .014, "dark")
    p("Camera yoke", "box", "metal", (-.31, 1.63, .54), (.18, .11, .11))
    p("Navigation bar", "box", "gold", (-.31, 1.70, .54), (.516, .038, .21))
    for side in (-1, 1):
        x = -.31 + side * .123
        p("Stereo camera housing", "beveled_box", "gold", (x, 1.766, .546), (.22, .122, .182))
        p("Stereo lens", "sphere", "black", (x, 1.773, .641), (.080, .077, .033))
        p("Stereo lens bezel", "cylinder", "metal", (x, 1.773, .670), (.098, .018, .098), angle=math.pi / 2)
    rover_strut(asset, "Dish support", (.35, .533, -.59), (.35, .861, -.59), .060, "foil")
    p("High gain dish", "sphere", "white", (.35, .893, -.57), (.340, .085, .340), angle=.46)
    p("Deck antenna cylinder", "cylinder", "metal", (-.49, .659, -.32), (.119, .236, .119))
    for side in (-1, 1):
        for z in (-.40, .35):
            detail_panel_grid(asset, (side * .79, .579, z), .60, .62, 4, 4, "solar", name="Zhurong petal cell seam")
            p("Petal hinge fastener", "sphere", "gold", (side * .46, .56, z), (.040, .030, .040))
    for step in range(8):
        angle = math.tau * step / 8
        rover_strut(asset, "Dish radial brace", (.35, .893, -.57),
                    (.35 + .20 * math.cos(angle), .90, -.57 + .20 * math.sin(angle)), .016, "metal")


def rosalind_body(asset, width, length, r, hub):
    p = asset.part
    light_rover_suspension(asset, width, length, r, hub)
    p("Insulated equipment housing", "rover_plate", "white", (0, .372, -.102), (width, .347, length * .86))
    p("Dark undertray", "rover_plate", "dark", (0, .199, -.121), (width * .88, .082, length * .77))
    p("Forward sample box", "beveled_box", "metal", (0, .386, .704), (.89, .283, .270))
    rover_array(asset, "Central photovoltaic deck", (0, .565, -.28), .79, 1.12)
    for side in (-1, 1):
        rover_array(asset, "Outboard solar wing", (side * .787, .557, -.30), .66, 1.13,
                    yaw=side * math.radians(-3))
        rover_flange(asset, "Wing hinge", (side * .46, .548, -.30), .083, .545, "dark")
        p("Side foil blanket", "box", "gold", (side * .54, .379, -.34), (.09, .18, .55))
    mast(asset, -.32, .557, .34, 1.12, .48, "metal")
    p("PanCam central instrument", "beveled_box", "white", (-.32, 1.80, .325), (.15, .105, .13))
    rover_strut(asset, "Camera harness", (-.268, .583, .281), (-.268, 1.453, .313), .025, "dark")
    p("Drill housing", "rover_plate", "metal", (.231, .412, .835), (.346, .641, .323))
    p("Drill housing cover", "box", "dark", (.231, .466, 1.00), (.264, .446, .026))
    p("Stowed drill collar", "cylinder", "metal", (.21, .13, .85), (.148, .147, .148))
    p("Close-up imager", "sphere", "black", (.055, .327, .983), (.096, .092, .079))
    detail_panel_grid(asset, (0, .768, -.28), .72, 1.02, 5, 4, "dark", name="Central deck seam")
    for side in (-1, 1):
        detail_panel_grid(asset, (side * .79, .768, -.30), .56, .98, 5, 4, "dark", name="Wing panel seam")
        for z in (-.65, -.30, .05):
            rover_strut(asset, "Wing harness", (side * .52, .62, z), (side * .79, .63, z), .016, "gold")
    detail_bolt_ring(asset, (.231, .49, .985), .105, count=10, bolt=.024, color="gold",
                     name="Drill housing fastener")
    for step in range(8):
        angle = math.tau * step / 8
        p("Drill collar tooth", "box", "metal",
          (.21 + .16 * math.cos(angle), .13, .85 + .16 * math.sin(angle)), (.025, .045, .055), angle=angle)


ROBOT_PROFILES = {
    "perseverance": (1.52, 2.35, .26, "metal",
                     "https://science.nasa.gov/mission/mars-2020-perseverance/rover-components/"),
    "small_rover": (1.44, 2.33, .25, "dark",
                    "https://science.nasa.gov/wp-content/uploads/2024/03/44706_MSLCuriosityBrochure.pdf"),
    "sojourner": (.42, .62, .065, "black", "https://science.nasa.gov/photojournal/rovers-and-sojourner/"),
    "mer": (.91, 1.29, .13, "metal", "https://science.nasa.gov/mission/mer-spirit/"),
    "zhurong": (1.19, 2.02, .17, "dark",
                "https://www.cnsa.gov.cn/english/n6465652/n6465653/c6840321/content.html"),
    "rosalind_franklin": (1.14, 1.81, .15, "metal",
                         "https://explorationscience.esa.int/project/exomars-rosalind-franklin-rfm/"),
}


def robot(name, width, length, r, hub, url):
    if name in ("perseverance", "small_rover"):
        return msl_rover(name, url)
    if name == "mer":
        return mer_rover(url)
    asset = Asset(name, url)
    build_body = {"sojourner": sojourner_body, "zhurong": zhurong_body,
                  "rosalind_franklin": rosalind_body}[name]
    build_body(asset, width, length, r, hub)
    return asset


OPEN_REF = "https://science.nasa.gov/resource/apollo-17-gene-cernan-in-lunar-roving-vehicle/"
SEV_REF = "https://science.nasa.gov/3d-resources/space-exploration-vehicle/"
BIKE_REF = "https://ntrs.nasa.gov/api/citations/20200002475/downloads/20200002475.pdf"


def crew(name, kind):
    references = {
        "two_wheel": "https://www.artstation.com/artwork/vbelO6",
        "four_wheel": "https://www.nasa.gov/wp-content/uploads/2020/06/draw_ltv_final-1.pdf",
        "unpressurized_rover": OPEN_REF,
        "pressurized_rover": SEV_REF,
        "buggy": "https://3dassets.dev/assets/lunar-surface-colony-and-rovers-pressurised-long-range-35466e96",
    }
    asset = Asset(name, references[name])
    p = asset.part

    def rail(label, start, end, diameter, color):
        a, b = np.asarray(start), np.asarray(end)
        delta = b - a
        length = float(np.linalg.norm(delta))
        direction = delta / length
        axis = np.cross((0, 1, 0), direction)
        sine = float(np.linalg.norm(axis))
        turn = math.atan2(sine, direction[1])
        axis = (axis / sine).tolist() if sine > 1e-9 else AXLE
        p(label, "cylinder", color, ((a + b) * .5).tolist(), (diameter, length, diameter), angle=turn, axis=axis)

    def surface(label, color, faces, center):
        positions, normals, triangles = [], [], []
        for polygon in faces:
            points = np.asarray(polygon)
            normal = np.cross(points[1] - points[0], points[2] - points[0])
            normal /= np.linalg.norm(normal)
            if np.dot(normal, points.mean(axis=0) - center) < 0:
                points, normal = points[::-1], -normal
            offset = len(positions)
            positions.extend(points)
            normals.extend([normal] * len(points))
            for i in range(1, len(points) - 1):
                triangles.extend((offset, offset + i, offset + i + 1))
        asset.geometry[label] = {
            "attributes": {
                "POSITION": asset.accessor(positions, "<f4", 5126, "VEC3", 34962, bounds=True),
                "NORMAL": asset.accessor(normals, "<f4", 5126, "VEC3", 34962),
            },
            "indices": asset.accessor(triangles, "<u2", 5123, "SCALAR", 34963),
        }
        p(label, label, color, (0, 0, 0), (1, 1, 1))

    def shell(label, color, sections, profile):
        rings = [[(width * x, floor + (roof - floor) * y, z) for x, y in profile]
                 for z, width, floor, roof in sections]
        faces = [rings[0], rings[-1]]
        for rear, front in zip(rings, rings[1:]):
            for i in range(len(profile)):
                j = (i + 1) % len(profile)
                # Split each wall so unequal chamfers remain planar.
                faces.extend(([rear[i], rear[j], front[j]], [rear[i], front[j], front[i]]))
        surface(label, color, faces, np.asarray(rings).mean(axis=(0, 1)))

    def fender(x, z, axle_height, radius, width, color):
        for i in range(-5, 6):
            angle = i * .24
            p("Wheel arch", "box", color, (x, axle_height + radius * math.cos(angle), z + radius * math.sin(angle)),
              (width, .048, radius * .25), angle=angle)

    def dish(x, y, z, radius, color):
        faces = []
        for i in range(12):
            a = math.tau * i / 12
            b = math.tau * (i + 1) / 12
            tip = (x, y, z)
            rim_a = (x + radius * math.cos(a), y + radius * .29, z + radius * math.sin(a))
            rim_b = (x + radius * math.cos(b), y + radius * .29, z + radius * math.sin(b))
            faces.append([tip, rim_a, rim_b])
        surface("Antenna reflector", color, faces, (x, y - radius, z))
        asset.data["materials"][asset.materials[color]]["doubleSided"] = True
        rail("Antenna feed stem", (x, y, z), (x, y + radius * .54, z), .025, "metal")
        p("Antenna feed", "sphere", "dark", (x, y + radius * .54, z), (.053, .058, .053))

    chamfered = [(-.73, 0), (.73, 0), (1, .23), (1, .71), (.73, 1), (-.73, 1), (-1, .71), (-1, .23)]
    if kind == "bike":
        for z, r in [(-.99, .394), (1.00, .46)]:
            rotor = wheel(asset, 0, z, r, .195, "metal")
            for side in (-1, 1):
                across = math.pi / 2
                p("Solid wheel disc", "cylinder", "white", (side * .097, 0, 0),
                  (r * 1.79, .030, r * 1.79), rotor, across, (0, 0, 1))
                p("Dark central drive hub", "cylinder", "black", (side * .115, 0, 0),
                  (r * .63, .034, r * .63), rotor, across, (0, 0, 1))
            for i in range(-2, 3):
                angle = i * .22
                arch = r + .025
                p("White wheel crown", "box", "white", (0, r + arch * math.cos(angle), z + arch * math.sin(angle)),
                  (.205, .026, arch * .23), angle=angle)
        shell("Boxed main battery pack", "metal",
              [(-.54, .147, .40, .79), (-.39, .192, .36, .88), (.44, .177, .39, .86), (.60, .124, .53, .87)],
              chamfered)
        p("Saddle", "sphere", "black", (0, .944, -.237), (.284, .105, .668), angle=.08)
        p("Aft gold sphere", "sphere", "gold", (0, .771, -.648), (.267, .267, .267))
        for side in (-1, 1):
            x = side * .133
            rail("Front suspension fork", (x, .482, 1.00), (x, .985, .535), .070, "metal")
            rail("Fork orange sleeve", (x, .552, .934), (x, .883, .630), .081, "orange")
            rail("Rear chainstay", (x, .403, -.99), (x, .541, -.38), .074, "dark")
            rail("Rear upper stay", (x, .403, -.99), (x, .855, -.54), .037, "dark")
            rail("Trellis diagonal", (x, .411, -.30), (x, .888, .48), .042, "dark")
            rail("Lower frame rail", (x, .408, -.37), (x, .449, .45), .040, "dark")
            p("White pivot cover", "sphere", "white", (side * .193, .785, .342), (.037, .172, .41), angle=.15)
            rail("Rear rack frame", (x, .938, -.31), (x, .918, -.92), .031, "dark")
            rail("Foot peg", (side * .128, .407, -.02), (side * .273, .407, -.02), .048, "metal")
        rail("Handlebar stem", (0, .936, .545), (0, 1.123, .441), .05, "dark")
        rail("Handlebar", (-.286, 1.124, .430), (.286, 1.124, .430), .045, "dark")
        for x in (-.245, .245):
            p("Rubber hand grip", "cylinder", "rubber", (x, 1.124, .430), (.058, .119, .058), angle=math.pi / 2, axis=(0, 0, 1))
        p("Headlamp", "sphere", "cream", (0, .942, .649), (.092, .081, .043))
    elif kind == "open":
        apollo = name == "unpressurized_rover"
        track, wheelbase, r, tire_width = (.85, 1.08, .40, .225) if apollo else (.98, 1.22, .46, .32)
        for x in (-track, track):
            for z in (-wheelbase, wheelbase):
                rotor = wheel(asset, x, z, r, tire_width, "metal", "metal" if apollo else "rubber")
                fender(x, z, r, r + .065, tire_width + .13, "red" if apollo else "dark")
                far_side = math.copysign(tire_width * .52, x)
                p("Recessed wheel face", "cylinder", "dark", (far_side, 0, 0),
                  (r * 1.27, .018, r * 1.27), rotor, math.pi / 2, (0, 0, 1))
                p("Spinning silver hub", "cylinder", "metal", (far_side * 1.14, 0, 0),
                  (r * .63, .030, r * .63), rotor, math.pi / 2, (0, 0, 1))
                for i in range(3):
                    angle = math.tau * i / 3
                    p("Hub spoke", "box", "metal", (far_side * 1.12, r * .43 * math.cos(angle), r * .43 * math.sin(angle)),
                      (.026, r * .34, r * .093), rotor, angle)
            rail("Low chassis side rail", (x * .80, .53, -wheelbase * 1.13), (x * .80, .53, wheelbase * 1.13),
                 .065, "metal")
        p("Open footwell", "box", "metal" if apollo else "dark", (0, .505, 0), (track * 1.51, .095, wheelbase * 2.16))
        for x in (-.35, .35):
            p("Seat cushion", "box", "white" if apollo else "cream", (x, .693, -.284), (.50, .096, .517))
            p("Seat shoulder frame", "box", "metal" if apollo else "dark", (x, .963, -.568), (.51, .535, .059), angle=.12)
            p("Seat fabric", "box", "white" if apollo else "cream", (x, .961, -.530), (.411, .437, .052), angle=.12)
            for y in (.818, .930, 1.042):
                p("Seat webbing", "box", "dark", (x, y, -.497 + (y - .961) * .12), (.425, .023, .016))
        p("Control pedestal", "box", "metal", (0, .728, .455), (.236, .41, .377), angle=-.11)
        p("Instrument panel", "box", "white" if apollo else "dark", (0, .937, .452), (.337, .095, .277), angle=-.27)
        p("Control grip", "box", "red" if apollo else "metal", (0, 1.007, .247), (.135, .041, .047))
        if apollo:
            p("Aft stowage box", "box", "white", (0, .803, -1.119), (1.13, .535, .48))
            for x in (-.51, .51):
                rail("Aft instrument stanchion", (x, .69, -1.24), (x, 1.56, -1.24), .032, "metal")
                rail("Aft wire rack", (x, 1.05, -1.42), (x, 1.05, -.849), .053, "metal")
            p("Gold surface camera mount", "box", "foil", (.42, .751, 1.246), (.34, .31, .235))
            p("Surface camera", "box", "white", (.42, .947, 1.315), (.337, .142, .212))
            p("Lens barrel", "cylinder", "dark", (.42, .951, 1.43), (.073, .074, .073), angle=math.pi / 2)
            rail("High gain antenna mast", (.49, .763, 1.04), (.49, 1.717, 1.04), .038, "metal")
            dish(.49, 1.73, 1.04, .406, "gold")
        else:
            for x in (-.67, .67):
                rail("Upright roll cage bar", (x, .584, .71), (x, 1.73, .112), .059, "metal")
                rail("Aft roll cage brace", (x, 1.73, .112), (x, .66, -.853), .046, "metal")
                rail("Side rail", (x, .734, -.64), (x, .879, .483), .064, "metal")
            rail("Roll cage crossbar", (-.68, 1.73, .112), (.68, 1.73, .112), .057, "metal")
            p("Overhead communications antenna", "sphere", "metal", (0, 1.806, .115), (.33, .059, .247))
            for z in (-1.284, 1.11):
                p("Equipment rack", "box", "metal", (0, .68, z), (1.45, .13, .482))
                p("Equipment case", "box", "dark", (0, .832, z), (.965, .223, .365))
            for x in (-.48, .48):
                p("Front running light", "box", "white", (x, .657, 1.371), (.20, .055, .030))
    else:
        sev = name == "pressurized_rover"
        track, r = (1.10, .41) if sev else (1.10, .45)
        for x in (-track, track):
            for z in (-1.40, 0, 1.40):
                rotor = wheel(asset, x, z, r, .184 if sev else .233, "metal", "rubber" if sev else "metal")
                side = math.copysign(1, x)
                outside = side * .10
                if sev:
                    p("Inboard paired tire", "cylinder", "rubber", (-side * .205, 0, 0), (.812, .160, .812),
                      rotor, math.pi / 2, (0, 0, 1))
                    p("Inboard rim", "cylinder", "metal", (-side * .286, 0, 0), (.65, .043, .65),
                      rotor, math.pi / 2, (0, 0, 1))
                else:
                    fender(x, z, r, r + .065, .37, "metal")
                p("Wheel well", "cylinder", "dark", (outside, 0, 0), (r * 1.71, .037, r * 1.71),
                  rotor, math.pi / 2, (0, 0, 1))
                for i in range(8):
                    angle = math.tau * i / 8
                    p("Radial wheel spoke", "box", "cream" if sev else "white",
                      (outside * 1.17, r * .51 * math.cos(angle), r * .51 * math.sin(angle)),
                      (.037, r * .59, .029), rotor, angle)
                p("Wheel center cap", "cylinder", "metal", (outside * 1.33, 0, 0), (.247, .058, .247),
                  rotor, math.pi / 2, (0, 0, 1))
                rail("Suspension strut", (x * .84, .52, z), (x * .83, .96, z), .136, "foil" if sev else "metal")
            rail("Lower chassis rail", (x * .79, .65, -1.73), (x * .79, .65, 1.73), .09, "foil" if sev else "metal")
        p("Wheel platform", "box", "metal", (0, .782, 0), (1.91, .234, 3.69))
        if sev:
            shell("Tapered SEV pressure hull", "white",
                  [(-1.96, .783, 1.26, 2.36), (-1.64, 1.046, 1.05, 2.62),
                   (.66, 1.068, 1.05, 2.61), (1.38, 1.020, 1.17, 2.51),
                   (1.83, .878, 1.35, 2.27), (1.95, .712, 1.49, 2.02)], chamfered)
            for side in (-1, 1):
                p("Upper windscreen surround", "box", "metal", (side * .376, 2.184, 1.846),
                  (.665, .570, .061), angle=-.57)
                p("Upper windscreen pane", "box", "black", (side * .376, 2.194, 1.877), (.569, .474, .052), angle=-.57)
                p("Lower viewing port surround", "box", "metal", (side * .368, 1.632, 1.942), (.580, .347, .052), angle=.33)
                p("Lower viewing port", "box", "black", (side * .368, 1.623, 1.972), (.482, .286, .042), angle=.33)
                for z in (-1.396, -1.103, -.810, -.517):
                    p("Blue exterior solar wrap", "box", "solar", (side * 1.058, 1.933, z),
                      (.052, .714, .280))
                x = side * 1.052
                for label, color, size, offset in [
                    ("Airlock trim", "dark", .975, 0), ("Door rim", "metal", .843, .039),
                    ("Airlock hatch", "white", .729, .066),
                ]:
                    p(label, "cylinder", color, (x + side * offset, 1.899, .25), (size, .072, size),
                      angle=math.pi / 2, axis=(0, 0, 1))
                p("Airlock door handle", "box", "gold", (side * 1.162, 1.891, .424), (.042, .152, .03))
                p("Forward side viewport", "box", "dark", (side * 1.038, 1.988, .976), (.060, .317, .319), angle=.12)
                rail("Roof whip antenna", (side * .522, 2.612, .884), (side * .560, 3.067, .963), .019, "metal")
                p("Forward camera pod", "box", "dark", (side * .496, 2.490, 1.307), (.133, .117, .192))
            p("Roof radiator", "box", "metal", (0, 2.622, -.340), (1.402, .042, 2.213))
            for x in (-.575, -.345, -.115, .115, .345, .575):
                p("Roof radiator groove", "box", "dark", (x, 2.645, -.325), (.013, .008, 2.026))
        else:
            shell("Buggy rounded rectangular cabin", "white",
                  [(-2.04, .791, 1.12, 2.36), (-1.73, 1.023, 1.01, 2.55),
                   (1.13, 1.043, 1.01, 2.55), (1.64, .992, 1.07, 2.24), (1.89, .819, 1.145, 1.86)],
                  chamfered)
            p("Buggy front glass surround", "box", "dark", (0, 1.988, 1.814), (1.314, .673, .068), angle=-.48)
            p("Buggy front glass", "box", "glass", (0, 1.993, 1.85), (1.115, .514, .054), angle=-.48)
            for side in (-1, 1):
                p("Rectangular side window trim", "box", "dark", (side * 1.041, 1.999, .281), (.049, .437, 1.25))
                p("Rectangular side window", "box", "glass", (side * 1.071, 1.999, .281), (.037, .312, 1.098))
                p("Circular front headlamp", "sphere", "cream", (side * .493, 1.315, 1.894), (.133, .135, .087))
                p("Lower front bumper end", "box", "gold", (side * .60, 1.092, 1.887), (.625, .087, .086))
            for z in (.80, .955, 1.11):
                p("Forward roof sunshade vane", "box", "metal", (0, 2.579, z), (1.63, .10, .036))
        for x in (-.402, .402):
            p("Roof solar frame", "box", "metal", (x, 2.581, -.465), (.74, .042, 1.59))
            for z in (-.995, -.465, .065):
                p("Roof solar cell bank", "box", "solar", (x, 2.607, z), (.71, .014, .505))
            p("Rear airlock outer collar", "cylinder", "metal", (0, 1.771, -1.977), (.922, .322, .922), angle=math.pi / 2)
            p("Rear airlock face", "cylinder", "white", (0, 1.771, -2.149), (.781, .076, .781), angle=math.pi / 2)
            rail("Roof dish mast", (.613, 2.56, -1.38), (.613, 2.952, -1.38), .053, "metal")
            dish(.613, 2.958, -1.38, .264, "metal")
    # High-poly crew-vehicle detail pass. These are deliberately small exterior
    # parts: harnesses, rack crossbars, panel seams, and service fasteners.
    if kind == "bike":
        detail_panel_grid(asset, (0, .36, -.06), .66, .52, 3, 4, "dark", name="Bike battery seam")
        for z in (-.98, 1.00):
            detail_bolt_ring(asset, (0, .40, z), .15, count=10, bolt=.018, color="metal", name="Bike axle bolt")
        for side in (-1, 1):
            rail("Bike brake cable", (side * .21, 1.08, .48), (side * .17, .62, .91), .012, "dark")
    elif kind == "open":
        for x in (-.35, .35):
            p("Seat lap belt", "box", "red" if apollo else "dark", (x, .835, -.02), (.055, .025, .42), angle=.10)
            p("Seat buckle", "box", "metal", (x, .83, .18), (.075, .048, .06))
        for z in (-wheelbase * 1.10, wheelbase * 1.10):
            rail("Rack upper crossbar", (-track * .78, 1.02, z), (track * .78, 1.02, z), .034, "metal")
            rail("Rack lower crossbar", (-track * .78, .73, z), (track * .78, .73, z), .027, "dark")
        detail_bolt_ring(asset, (0, .55, 0), .22, count=8, bolt=.025, color="metal", name="Open chassis bolt")
    else:
        for z in (-1.20, -.55, .10, .75, 1.40):
            p("Cabin side service seam", "box", "dark", (1.12, 1.48, z), (.025, .025, .48))
        for side in (-1, 1):
            detail_bolt_ring(asset, (side * 1.07, 1.90, .25), .38, count=12, bolt=.024,
                             color="gold", name="Airlock fastener")
            rail("Cabin sensor cable", (side * .48, 2.48, .98), (side * 1.02, 2.16, .88), .020, "gold")
        detail_panel_grid(asset, (0, 2.65, -.45), 1.28, 1.78, 5, 6, "dark", name="Roof panel seam")
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
