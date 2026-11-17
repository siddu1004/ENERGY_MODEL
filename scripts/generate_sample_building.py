"""Generate a SYNTHETIC sample building model as USDZ.

This is a stand-in for a real RoomPlan / LiDAR scan until actual client
files are available. It deliberately contains ONLY what a real scan would
contain: geometry (floors, walls, windows, doors, a few furniture boxes).

It does NOT contain (because real scans don't either):
  - wall / glazing materials, U-values, SHGC
  - which walls are exterior vs interior (must be inferred from geometry)
  - compass orientation (true north is unknown)
  - ceilings as separate surfaces (ceiling area = floor area, assumed flat)
  - HVAC zoning, occupancy, equipment

Layout: one office floor, 30 m x 20 m = 600 m2, clear height 2.7 m.
Units: metres, Y-up (same convention as Apple RoomPlan exports).

Outputs:
  sample_data/sample_building.usdz
  sample_data/sample_building_ground_truth.json  (expected areas, for tests)
  sample_data/sample_building_plan.png           (top-down preview)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdUtils, Vt

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "sample_data"

CEILING_HEIGHT_M = 2.7

# (name, x0, z0, x1, z1)  -- rectangle on the floor plane
ROOMS = [
    ("Open_Office", 0, 0, 18, 12),
    ("Manager_Office_1", 18, 0, 24, 6),
    ("Manager_Office_2", 24, 0, 30, 6),
    ("Conference_Room", 18, 6, 30, 12),
    ("Corridor", 0, 12, 30, 14),
    ("Server_Room", 0, 14, 6, 20),
    ("Pantry", 6, 14, 12, 20),
    ("Restrooms", 12, 14, 18, 20),
    ("Reception_Lobby", 18, 14, 30, 20),
]

# Openings per room and side. Sides are generator-internal labels only
# ('S' = z0 edge, 'N' = z1 edge, 'W' = x0 edge, 'E' = x1 edge); they are
# NOT compass directions and are NOT written to the file.
# Each opening: (kind, offset_from_wall_start_m, width_m, sill_m, height_m)
W = ("Window",)
OPENINGS = {
    "Open_Office": {
        "S": [W + (1.0 + 3.0 * i, 1.8, 0.9, 1.5) for i in range(6)],
        "W": [W + (1.5 + 3.5 * i, 1.8, 0.9, 1.5) for i in range(3)],
        "E": [("Door", 9.0, 0.9, 0.0, 2.1)],
        "N": [("Door", 8.0, 1.2, 0.0, 2.1)],
    },
    "Manager_Office_1": {
        "S": [W + (1.0, 1.8, 0.9, 1.5), W + (3.5, 1.8, 0.9, 1.5)],
        "W": [("Door", 4.5, 0.9, 0.0, 2.1)],
    },
    "Manager_Office_2": {
        "S": [W + (1.0, 1.8, 0.9, 1.5), W + (3.5, 1.8, 0.9, 1.5)],
        "E": [W + (2.0, 1.8, 0.9, 1.5)],
        "W": [("Door", 0.6, 0.9, 0.0, 2.1)],
    },
    "Conference_Room": {
        "E": [W + (0.8, 1.8, 0.9, 1.5), W + (3.4, 1.8, 0.9, 1.5)],
        "N": [("Door", 5.0, 1.2, 0.0, 2.1)],
    },
    "Corridor": {},
    "Server_Room": {
        "W": [W + (2.0, 1.2, 1.2, 1.0)],
        "S": [("Door", 2.5, 0.9, 0.0, 2.1)],
    },
    "Pantry": {
        "N": [W + (2.1, 1.8, 0.9, 1.5)],
        "S": [("Door", 2.5, 0.9, 0.0, 2.1)],
    },
    "Restrooms": {
        "N": [W + (1.0, 0.8, 1.8, 0.6), W + (4.2, 0.8, 1.8, 0.6)],
        "S": [("Door", 2.5, 0.9, 0.0, 2.1)],
    },
    "Reception_Lobby": {
        "N": [("Door", 5.1, 1.8, 0.0, 2.1),  # main glass entrance
              W + (0.8, 1.8, 0.9, 1.5), W + (8.5, 1.8, 0.9, 1.5)],
        "E": [W + (2.1, 1.8, 0.9, 1.5)],
        "S": [("Door", 5.4, 1.2, 0.0, 2.1)],
    },
}

# A few furniture objects, like RoomPlan "Object" detections. A parser
# must ignore these for envelope area calculations.
FURNITURE = [
    ("Open_Office", "Table", (2, 0, 2), (8, 0.75, 3.6)),
    ("Open_Office", "Table", (2, 0, 6), (8, 0.75, 7.6)),
    ("Open_Office", "Table", (10, 0, 2), (16, 0.75, 3.6)),
    ("Open_Office", "Table", (10, 0, 6), (16, 0.75, 7.6)),
    ("Conference_Room", "Table", (21, 0, 8), (27, 0.75, 10)),
    ("Server_Room", "Storage", (0.5, 0, 15), (1.3, 2.0, 19)),
    ("Pantry", "Refrigerator", (10.8, 0, 18.8), (11.7, 1.8, 19.6)),
]


def wall_edges(x0, z0, x1, z1):
    """Return {side: (start_xz, end_xz)} walking each edge from its start."""
    return {
        "S": ((x0, z0), (x1, z0)),
        "E": ((x1, z0), (x1, z1)),
        "N": ((x1, z1), (x0, z1)),
        "W": ((x0, z1), (x0, z0)),
    }


def quad_on_wall(start, end, offset, width, y0, y1):
    """Vertical rectangle lying in the wall plane."""
    (sx, sz), (ex, ez) = start, end
    length = ((ex - sx) ** 2 + (ez - sz) ** 2) ** 0.5
    ux, uz = (ex - sx) / length, (ez - sz) / length
    a = (sx + ux * offset, sz + uz * offset)
    b = (sx + ux * (offset + width), sz + uz * (offset + width))
    return [
        Gf.Vec3f(a[0], y0, a[1]),
        Gf.Vec3f(b[0], y0, b[1]),
        Gf.Vec3f(b[0], y1, b[1]),
        Gf.Vec3f(a[0], y1, a[1]),
    ]


def add_mesh(stage, path, points, category):
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr(Vt.Vec3fArray(points))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray([len(points)]))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray(list(range(len(points)))))
    mesh.CreateDoubleSidedAttr(True)
    mesh.GetPrim().SetCustomDataByKey("category", category)
    return mesh


def add_box(stage, path, mn, mx, category):
    (x0, y0, z0), (x1, y1, z1) = mn, mx
    pts = [Gf.Vec3f(*p) for p in [
        (x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1),
        (x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)]]
    faces = [0, 1, 2, 3, 4, 7, 6, 5, 0, 4, 5, 1, 1, 5, 6, 2, 2, 6, 7, 3, 3, 7, 4, 0]
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr(Vt.Vec3fArray(pts))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray([4] * 6))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray(faces))
    mesh.GetPrim().SetCustomDataByKey("category", category)


def build(usdc_path: Path) -> dict:
    stage = Usd.Stage.CreateNew(str(usdc_path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/Building")
    stage.SetDefaultPrim(root.GetPrim())
    stage.SetMetadata("comment", "SYNTHETIC sample building - not a real scan. "
                      "Geometry only; no materials, orientation or HVAC data.")

    h = CEILING_HEIGHT_M
    truth = {"ceiling_height_m": h, "rooms": {}}

    for name, x0, z0, x1, z1 in ROOMS:
        rp = f"/Building/Rooms/{name}"
        UsdGeom.Xform.Define(stage, rp)
        add_mesh(stage, f"{rp}/Floor", [
            Gf.Vec3f(x0, 0, z0), Gf.Vec3f(x1, 0, z0),
            Gf.Vec3f(x1, 0, z1), Gf.Vec3f(x0, 0, z1)], "Floor")

        room = {
            "floor_area_m2": (x1 - x0) * (z1 - z0),
            "volume_m3": (x1 - x0) * (z1 - z0) * h,
            "dimensions_m": [x1 - x0, z1 - z0, h],
            "walls": [],
        }
        for i, (side, (s, e)) in enumerate(wall_edges(x0, z0, x1, z1).items()):
            length = abs(e[0] - s[0]) + abs(e[1] - s[1])
            wp = f"{rp}/Walls/Wall_{i}"
            add_mesh(stage, wp, quad_on_wall(s, e, 0, length, 0, h), "Wall")
            # exterior = lies on the building outline (0..30 x 0..20)
            exterior = (s[0] == e[0] and s[0] in (0, 30)) or \
                       (s[1] == e[1] and s[1] in (0, 20))
            win_area = door_area = 0.0
            for j, (kind, off, w, sill, oh) in enumerate(OPENINGS[name].get(side, [])):
                assert off + w <= length, (name, side, off, w)
                add_mesh(stage, f"{wp}/{kind}_{j}",
                         quad_on_wall(s, e, off, w, sill, sill + oh), kind)
                if kind == "Window":
                    win_area += w * oh
                else:
                    door_area += w * oh
            room["walls"].append({
                "prim": f"Wall_{i}", "length_m": length,
                "gross_area_m2": round(length * h, 4),
                "window_area_m2": round(win_area, 4),
                "door_area_m2": round(door_area, 4),
                "exterior": exterior,
            })
        truth["rooms"][name] = room

    for k, (room_name, cat, mn, mx) in enumerate(FURNITURE):
        add_box(stage, f"/Building/Rooms/{room_name}/Objects/{cat}_{k}", mn, mx, cat)

    stage.GetRootLayer().Save()

    rooms = truth["rooms"].values()
    ext = [w for r in rooms for w in r["walls"] if w["exterior"]]
    truth["totals"] = {
        "floor_area_m2": sum(r["floor_area_m2"] for r in rooms),
        "ceiling_area_m2": sum(r["floor_area_m2"] for r in rooms),
        "volume_m3": round(sum(r["volume_m3"] for r in rooms), 4),
        "exterior_wall_gross_area_m2": round(sum(w["gross_area_m2"] for w in ext), 4),
        "exterior_window_area_m2": round(sum(w["window_area_m2"] for w in ext), 4),
        "window_to_wall_ratio": round(sum(w["window_area_m2"] for w in ext) /
                                      sum(w["gross_area_m2"] for w in ext), 4),
    }
    truth["NOT_IN_MODEL"] = [
        "wall/roof/glazing materials and U-values",
        "glazing SHGC / shading",
        "true-north orientation",
        "exterior vs interior wall flag (inferred here from the outline)",
        "number of floors / whole-building size",
        "occupancy, lighting, equipment, HVAC zoning",
    ]
    return truth


def plot_plan(truth: dict, png: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 7), dpi=150)
    for name, x0, z0, x1, z1 in ROOMS:
        ax.add_patch(plt.Rectangle((x0, z0), x1 - x0, z1 - z0, fill=True,
                                   facecolor="#eef2f7", edgecolor="#334", lw=1.2))
        ax.text((x0 + x1) / 2, (z0 + z1) / 2,
                f"{name.replace('_', ' ')}\n{truth['rooms'][name]['floor_area_m2']} m²",
                ha="center", va="center", fontsize=8)
        for side, (s, e) in wall_edges(x0, z0, x1, z1).items():
            length = abs(e[0] - s[0]) + abs(e[1] - s[1])
            ux, uz = (e[0] - s[0]) / length, (e[1] - s[1]) / length
            for kind, off, w, *_ in OPENINGS[name].get(side, []):
                a = (s[0] + ux * off, s[1] + uz * off)
                b = (s[0] + ux * (off + w), s[1] + uz * (off + w))
                ax.plot([a[0], b[0]], [a[1], b[1]],
                        color="#2a8fd6" if kind == "Window" else "#d9822b", lw=4)
    for _, cat, mn, mx in FURNITURE:
        ax.add_patch(plt.Rectangle((mn[0], mn[2]), mx[0] - mn[0], mx[2] - mn[2],
                                   facecolor="#ccc", edgecolor="#999", lw=0.5))
    ax.plot([], [], color="#2a8fd6", lw=4, label="Window")
    ax.plot([], [], color="#d9822b", lw=4, label="Door")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1))
    ax.set_xlim(-1, 31); ax.set_ylim(-1, 21); ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.set_xlabel("x (m)"); ax.set_ylabel("z (m)")
    t = truth["totals"]
    ax.set_title(f"SYNTHETIC sample floor — {t['floor_area_m2']} m², "
                 f"h={CEILING_HEIGHT_M} m, WWR={t['window_to_wall_ratio']:.0%} "
                 "(north unknown)", fontsize=10)
    fig.tight_layout()
    fig.savefig(png)


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        usdc = Path(tmp) / "sample_building.usdc"
        truth = build(usdc)
        usdz = OUT_DIR / "sample_building.usdz"
        usdz.unlink(missing_ok=True)
        assert UsdUtils.CreateNewUsdzPackage(Sdf.AssetPath(str(usdc)), str(usdz))
    (OUT_DIR / "sample_building_ground_truth.json").write_text(json.dumps(truth, indent=2))
    plot_plan(truth, OUT_DIR / "sample_building_plan.png")
    print(json.dumps(truth["totals"], indent=2))


if __name__ == "__main__":
    main()
