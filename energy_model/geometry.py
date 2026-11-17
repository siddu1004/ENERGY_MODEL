"""Extract building geometry from a USDZ model.

Reads only geometry. Anything thermal (materials, U-values, orientation) is
NOT in the file and must come from the parameter registry.

Conventions (match the sample file and Apple ARKit/RoomPlan):
  metres, Y-up; with gravity-and-heading alignment -Z = north, +X = east.
  A real scan's true north is unknown unless the capture app recorded it,
  so `north_offset_deg` rotates the whole building and is an ASSUMPTION.

Exterior vs interior walls are not labelled in a scan. They are inferred:
a wall segment that coincides with another room's wall is interior; the
rest is exterior. (A wall facing an unscanned space would be misclassified
as exterior - one reason the engineer must review the result.)

NOTE: written against the synthetic sample's prim layout
(/Building/Rooms/<room>/{Floor, Walls/Wall_i/{Window_j, Door_k}}) with a
`category` customData key. Real RoomPlan exports use a different hierarchy
and will need an adapter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from pxr import Usd, UsdGeom

TOL = 1e-3


@dataclass
class Opening:
    kind: str          # "Window" | "Door"
    width: float
    height: float
    sill: float
    t_mid: float       # position of opening centre along wall, metres from wall start
    exterior: bool = False

    @property
    def area(self):
        return self.width * self.height


@dataclass
class Wall:
    room: str
    name: str
    p0: np.ndarray     # (x, z) start
    p1: np.ndarray     # (x, z) end
    height: float
    normal: np.ndarray = None          # outward (x, z) unit vector
    openings: list[Opening] = field(default_factory=list)
    interior_intervals: list[tuple[float, float]] = field(default_factory=list)

    @property
    def length(self):
        return float(np.linalg.norm(self.p1 - self.p0))

    @property
    def gross_area(self):
        return self.length * self.height

    @property
    def exterior_length(self):
        return max(0.0, self.length - sum(b - a for a, b in self.interior_intervals))

    @property
    def exterior_gross_area(self):
        return self.exterior_length * self.height

    def exterior_openings(self, kind=None):
        return [o for o in self.openings if o.exterior and (kind is None or o.kind == kind)]

    @property
    def exterior_opaque_area(self):
        return self.exterior_gross_area - sum(o.area for o in self.exterior_openings())

    def azimuth(self, north_offset_deg=0.0):
        """Compass azimuth of the outward normal (0=N, 90=E, 180=S, 270=W)."""
        nx, nz = self.normal
        return (math.degrees(math.atan2(nx, -nz)) + north_offset_deg) % 360


@dataclass
class Room:
    name: str
    floor_polygon: np.ndarray   # (n, 2) x,z
    height: float
    walls: list[Wall] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)

    @property
    def floor_area(self):
        x, z = self.floor_polygon[:, 0], self.floor_polygon[:, 1]
        return 0.5 * abs(np.dot(x, np.roll(z, 1)) - np.dot(z, np.roll(x, 1)))

    @property
    def volume(self):
        return self.floor_area * self.height

    @property
    def centroid(self):
        return self.floor_polygon.mean(axis=0)

    @property
    def is_perimeter(self):
        return any(w.exterior_length > TOL for w in self.walls)


@dataclass
class Building:
    rooms: dict[str, Room]
    up_axis: str
    meters_per_unit: float

    @property
    def floor_area(self):
        return sum(r.floor_area for r in self.rooms.values())

    @property
    def volume(self):
        return sum(r.volume for r in self.rooms.values())

    def walls(self):
        return [w for r in self.rooms.values() for w in r.walls]

    def summary(self):
        ext = [w for w in self.walls() if w.exterior_length > TOL]
        win = sum(o.area for w in ext for o in w.exterior_openings("Window"))
        gross = sum(w.exterior_gross_area for w in ext)
        return {
            "rooms": len(self.rooms),
            "floor_area_m2": self.floor_area,
            "volume_m3": self.volume,
            "exterior_wall_gross_area_m2": gross,
            "exterior_window_area_m2": win,
            "window_to_wall_ratio": win / gross if gross else 0.0,
        }


def _points(prim):
    return np.array(UsdGeom.Mesh(prim).GetPointsAttr().Get(), dtype=float)


def load_usdz(path) -> Building:
    stage = Usd.Stage.Open(str(path))
    up = UsdGeom.GetStageUpAxis(stage)
    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    if up != "Y":
        raise ValueError(f"expected Y-up model, got {up}")

    rooms: dict[str, Room] = {}
    rooms_root = stage.GetPrimAtPath("/Building/Rooms")
    for rprim in rooms_root.GetChildren():
        name = rprim.GetName()
        floor, walls, objects = None, [], []
        for prim in Usd.PrimRange(rprim):
            if not prim.IsA(UsdGeom.Mesh):
                continue
            cat = prim.GetCustomDataByKey("category")
            pts = _points(prim) * mpu
            if cat == "Floor":
                floor = pts[:, [0, 2]]
            elif cat == "Wall":
                ys = pts[:, 1]
                walls.append(Wall(name, prim.GetName(), pts[0, [0, 2]], pts[1, [0, 2]],
                                  float(ys.max() - ys.min())))
                walls[-1]._prim = prim
            elif cat in ("Window", "Door"):
                pass  # handled with their parent wall
            else:
                objects.append(cat)          # furniture: ignored for envelope
        if floor is None:
            raise ValueError(f"room {name} has no floor")
        room = Room(name, floor, max(w.height for w in walls), walls, objects)
        for w in walls:
            # outward normal = perpendicular pointing away from the room centroid
            d = (w.p1 - w.p0) / w.length
            n = np.array([d[1], -d[0]])
            mid = (w.p0 + w.p1) / 2
            if np.dot(n, mid - room.centroid) < 0:
                n = -n
            w.normal = n
            for child in w._prim.GetChildren():
                cat = child.GetCustomDataByKey("category")
                if cat not in ("Window", "Door"):
                    continue
                p = _points(child) * mpu
                a, b = p[0, [0, 2]], p[1, [0, 2]]
                t_mid = float(np.dot((a + b) / 2 - w.p0, d))
                w.openings.append(Opening(cat, float(np.linalg.norm(b - a)),
                                          float(p[:, 1].max() - p[:, 1].min()),
                                          float(p[:, 1].min()), t_mid))
            del w._prim
        rooms[name] = room

    _classify_exterior(rooms)
    return Building(rooms, up, mpu)


def _classify_exterior(rooms: dict[str, Room]) -> None:
    """Mark wall segments shared with another room as interior."""
    walls = [w for r in rooms.values() for w in r.walls]
    for w in walls:
        d = (w.p1 - w.p0) / w.length
        for o in walls:
            if o.room == w.room:
                continue
            od = (o.p1 - o.p0) / o.length
            # colinear: parallel directions and o lies on w's line
            if abs(d[0] * od[1] - d[1] * od[0]) > TOL:
                continue
            off = o.p0 - w.p0
            if abs(d[0] * off[1] - d[1] * off[0]) > TOL:
                continue
            t0, t1 = sorted((float(np.dot(o.p0 - w.p0, d)), float(np.dot(o.p1 - w.p0, d))))
            a, b = max(0.0, t0), min(w.length, t1)
            if b - a > TOL:
                w.interior_intervals.append((a, b))
        w.interior_intervals = _merge(w.interior_intervals)
        for op in w.openings:
            op.exterior = not any(a - TOL <= op.t_mid <= b + TOL for a, b in w.interior_intervals)


def _merge(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + TOL:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out
