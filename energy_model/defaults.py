"""Default parameter set for the preliminary model, every value tagged.

Everything here that is ASSUMED is a candidate question for the engineer.
"""

from __future__ import annotations

from .provenance import Registry

# Room function is NOT in a scan (RoomPlan has no office room labels).
# In the sample the room names hint at use; keyword match -> profile.
# (m2 per person, lighting W/m2, equipment W/m2 or fixed W)
ROOM_PROFILES = {
    "office":     dict(m2_per_person=10, light=10, equip=15),
    "manager":    dict(m2_per_person=18, light=10, equip=15),
    "conference": dict(m2_per_person=4, light=12, equip=5),
    "corridor":   dict(m2_per_person=0, light=6, equip=0),
    "server":     dict(m2_per_person=0, light=8, equip_fixed_W=10000, always_on=True),
    "pantry":     dict(m2_per_person=10, light=10, equip=30),
    "restroom":   dict(m2_per_person=0, light=8, equip=0),
    "lobby":      dict(m2_per_person=10, light=12, equip=5),
}


def room_profile(name: str):
    n = name.lower()
    for key in ("manager", "conference", "corridor", "server", "pantry", "restroom",
                "lobby", "office"):
        if key in n:
            return key, ROOM_PROFILES[key]
    return "office", ROOM_PROFILES["office"]


def default_registry() -> Registry:
    r = Registry()
    A, C, H = "assumed", "constant", "hypothetical"

    # --- site & climate (location unknown) ---
    r.set("latitude_deg", 17.4, "deg N", A, "Placeholder hot-climate site; replace with real site")
    r.set("day_of_year", 141, "-", A, "21 May - pre-monsoon design day")
    r.set("T_out_max", 38.0, "°C", A, "Design dry-bulb max")
    r.set("T_out_range", 10.0, "°C", A, "Design daily range")
    r.set("w_out", 0.016, "kg/kg", A, "Outdoor humidity ratio (hot-humid)")
    r.set("north_offset_deg", 0.0, "deg", A,
          "Model -Z assumed = true north. Real scan orientation unknown")

    # --- indoor design ---
    r.set("T_in", 24.0, "°C", A, "Cooling setpoint")
    r.set("RH_in", 0.50, "-", A, "Indoor RH target")
    r.set("occ_start_h", 8, "h", H, "Matches 12 h/day operation")
    r.set("occ_end_h", 20, "h", H, "")

    # --- envelope (NOT in USDZ) ---
    r.set("U_wall", 1.5, "W/m²K", A, "Uninsulated masonry (brief's example value)")
    r.set("U_window", 5.8, "W/m²K", A, "Single glazing")
    r.set("SHGC", 0.50, "-", A, "Tinted single glazing")
    r.set("IAC", 0.80, "-", A, "Interior blinds attenuation")
    r.set("U_roof", 0.8, "W/m²K", A, "Only if this floor is the top floor")
    r.set("alpha_wall", 0.6, "-", A, "Solar absorptance, medium colour")
    r.set("alpha_roof", 0.7, "-", A, "")
    r.set("h_out", 17.0, "W/m²K", C, "Exterior film coefficient (ASHRAE summer)")
    r.set("exterior_doors_glazed", True, "-", A, "Entrance door treated as glass")
    r.set("floor_position", "intermediate", "-", A,
          "Scanned floor assumed to have floors above and below (no roof/ground)")

    # --- internal gains ---
    r.set("people_sensible_W", 75, "W/person", C, "ASHRAE office, moderately active")
    r.set("people_latent_W", 55, "W/person", C, "")
    r.set("offhours_light_frac", 0.05, "-", A, "")
    r.set("offhours_equip_frac", 0.20, "-", A, "")
    r.set("server_on_chiller", False, "-", A,
          "Server room assumed on its own 24 h cooling (CRAC/DX), NOT the chiller")

    # --- ventilation ---
    r.set("vent_L_s_person", 2.5, "L/s/person", C, "ASHRAE 62.1 office Rp")
    r.set("vent_L_s_m2", 0.3, "L/s/m²", C, "ASHRAE 62.1 office Ra")
    r.set("infiltration_ach", 0.2, "1/h", A, "Perimeter rooms, building slightly pressurised")

    # --- thermal mass (dynamic model) ---
    r.set("slab_active_thickness_m", 0.05, "m", A, "Per side (floor top + ceiling underside)")
    r.set("concrete_rho_cp", 2400 * 880, "J/m³K", C, "")
    r.set("h_mass_air", 3.0, "W/m²K", A, "Convective coupling slab <-> air")
    r.set("air_capacity_multiplier", 5.0, "-", A, "Furniture/partitions added to air node")
    r.set("radiant_frac_solar", 0.7, "-", A, "")
    r.set("radiant_frac_internal", 0.4, "-", A, "")

    # --- physics ---
    r.set("rho_air", 1.2, "kg/m³", C, "")
    r.set("cp_air", 1006.0, "J/kgK", C, "")
    r.set("h_fg", 2.501e6, "J/kg", C, "")
    return r
