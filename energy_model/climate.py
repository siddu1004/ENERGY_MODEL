"""Design-day outdoor conditions and clear-sky solar irradiance.

Simplified ASHRAE-style methods (sufficient for a preliminary design-day
estimate, NOT for annual simulation - that needs real hourly weather files):
  - dry-bulb profile: Tmax - DR * fraction(hour)  (ASHRAE daily-range table)
  - solar position: standard declination / hour-angle equations, solar time
    taken equal to clock time (equation of time + longitude ignored)
  - clear-sky beam: DN = A exp(-B / sin(altitude))  (ASHRAE 'A, B, C' model)
"""

from __future__ import annotations

import math

import numpy as np

# ASHRAE fraction of daily range below the maximum, hours 1..24 (index 0 = hour 1)
_DR_FRACTION = [0.87, 0.92, 0.96, 0.99, 1.00, 0.98, 0.93, 0.84, 0.71, 0.56, 0.39, 0.23,
                0.11, 0.03, 0.00, 0.03, 0.10, 0.21, 0.34, 0.47, 0.58, 0.68, 0.76, 0.82]


def outdoor_temp(hour: float, t_max: float, daily_range: float) -> float:
    """Dry-bulb at clock time `hour` (0-24, continuous)."""
    # table value k applies at clock hour k+1; interpolate cyclically
    h = (hour - 1) % 24
    i = int(h)
    f = h - i
    frac = _DR_FRACTION[i] * (1 - f) + _DR_FRACTION[(i + 1) % 24] * f
    return t_max - daily_range * frac


def sun_position(hour: float, latitude_deg: float, day_of_year: int):
    """Return (altitude_deg, azimuth_deg from north clockwise)."""
    L = math.radians(latitude_deg)
    dec = math.radians(23.45 * math.sin(math.radians(360 * (284 + day_of_year) / 365)))
    H = math.radians(15 * (hour - 12))
    sin_b = math.cos(L) * math.cos(dec) * math.cos(H) + math.sin(L) * math.sin(dec)
    beta = math.asin(max(-1.0, min(1.0, sin_b)))
    az = math.degrees(math.atan2(-math.sin(H),
                                 math.tan(dec) * math.cos(L) - math.sin(L) * math.cos(H)))
    return math.degrees(beta), az % 360


def irradiance(hour, surface_azimuth_deg, tilt_deg, latitude_deg, day_of_year,
               A=1104.0, B=0.196, C=0.121, ground_reflectance=0.2):
    """Total clear-sky irradiance (W/m2) on a surface.

    tilt 90 = vertical wall, tilt 0 = horizontal roof.
    """
    alt, az = sun_position(hour, latitude_deg, day_of_year)
    if alt <= 0:
        return 0.0
    sb = math.sin(math.radians(alt))
    dn = A * math.exp(-B / sb)
    t = math.radians(tilt_deg)
    # incidence angle cosine
    cos_i = (math.cos(math.radians(alt)) * math.cos(math.radians(az - surface_azimuth_deg)) * math.sin(t)
             + sb * math.cos(t))
    beam = dn * max(0.0, cos_i)
    view_sky = (1 + math.cos(t)) / 2
    view_gnd = (1 - math.cos(t)) / 2
    diffuse = C * dn * view_sky
    reflected = ground_reflectance * dn * (sb + C) * view_gnd
    return beam + diffuse + reflected


def humidity_ratio(t_c: float, rh: float, p_kpa: float = 101.325) -> float:
    """kg water / kg dry air from dry-bulb and relative humidity (Magnus)."""
    pws = 0.61094 * math.exp(17.625 * t_c / (t_c + 243.04))
    pw = rh * pws
    return 0.622 * pw / (p_kpa - pw)


def hours(step_h: float = 1.0):
    return np.arange(0, 24, step_h)
