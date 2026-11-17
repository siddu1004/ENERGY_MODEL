"""Component performance models for the chilled-water system.

Every model is either (a) a regression fitted to tabulated data, or (b) a
physics-based relation with stated, assumed parameters. All powers in kW,
temperatures in °C, flow / speed as fractions of design.

  Chiller : P = poly(L, CHWS, ECWT)  - 10-term quadratic regression, fitted
            capacity = linear(CHWS, ECWT) - fitted
  Coil    : sensible capacity by ε-NTU (counter-flow), UA from air- and
            water-side film resistances scaling with flow^0.8
  Pump/fan: P = P0 · f · (c + (1-c) f²)   affinity law with a fixed-pressure
            (control setpoint / static) fraction c
  Tower   : approach = A0 · (Q_rej/Q_rej0) · f_t^-0.6 ;  P = P0 · f_t³
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from openpyxl import load_workbook

TR = 3.51685


# ----------------------------------------------------------------- chiller
def _features(L, Ts, Tc):
    L, Ts, Tc = np.broadcast_arrays(np.asarray(L, float), np.asarray(Ts, float), np.asarray(Tc, float))
    return np.stack([np.ones_like(L), L, L * L, Ts, Ts * Ts, Tc, Tc * Tc, L * Ts, L * Tc, Ts * Tc], -1)


FEATURE_NAMES = ["1", "L", "L²", "Ts", "Ts²", "Tc", "Tc²", "L·Ts", "L·Tc", "Ts·Tc"]


@dataclass
class ChillerModel:
    coef: np.ndarray            # power regression (L in TR)
    cap_coef: np.ndarray        # capacity_TR = c0 + c1·Ts + c2·Tc
    domain: dict                # validity range of the data
    stats: dict                 # fit diagnostics

    def power(self, Q_kW, Ts, Tc):
        return _features(np.asarray(Q_kW) / TR, Ts, Tc) @ self.coef

    def capacity_kW(self, Ts, Tc):
        return (self.cap_coef[0] + self.cap_coef[1] * Ts + self.cap_coef[2] * Tc) * TR

    def dP_dTs(self, Q_kW, Ts, Tc):
        """Analytic partial derivative of power w.r.t. CHWS (kW/K)."""
        L = Q_kW / TR
        c = self.coef
        return c[3] + 2 * c[4] * Ts + c[7] * L + c[9] * Tc

    def dP_dTc(self, Q_kW, Ts, Tc):
        L = Q_kW / TR
        c = self.coef
        return c[5] + 2 * c[6] * Tc + c[8] * L + c[9] * Ts


def fit_chiller(xlsx, test_frac=0.2, seed=0) -> ChillerModel:
    ws = load_workbook(xlsx, data_only=True)["Chiller_PartLoad_Data"]
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if isinstance(r[0], (int, float))]
    d = np.array([[r[0], r[1], r[2], r[3], r[5]] for r in rows], float)  # L, Ts, Tc, cap, P
    L, Ts, Tc, cap, P = d.T
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(d))
    n_test = int(len(d) * test_frac)
    te, tr = idx[:n_test], idx[n_test:]

    X = _features(L, Ts, Tc)
    coef_tr, *_ = np.linalg.lstsq(X[tr], P[tr], rcond=None)
    rmse = lambda y, yh: float(np.sqrt(np.mean((y - yh) ** 2)))  # noqa: E731
    test_rmse = rmse(P[te], X[te] @ coef_tr)
    coef, *_ = np.linalg.lstsq(X, P, rcond=None)         # final fit on all data
    pred = X @ coef
    r2 = 1 - ((P - pred) ** 2).sum() / ((P - P.mean()) ** 2).sum()

    Xc = np.stack([np.ones_like(Ts), Ts, Tc], -1)
    cap_coef, *_ = np.linalg.lstsq(Xc, cap, rcond=None)

    model = ChillerModel(coef, cap_coef,
                         dict(Ts=(Ts.min(), Ts.max()), Tc=(Tc.min(), Tc.max()),
                              PLR_min=float((L / cap).min())),
                         dict(n=len(d), r2=float(r2), rmse_kW=rmse(P, pred), test_rmse_kW=test_rmse,
                              n_test=n_test, cap_rmse_TR=rmse(cap, Xc @ cap_coef)))
    # physics sanity checks of the regression over its domain
    g = np.array([[q, t, c] for q in np.linspace(0.3, 1, 8) * 250 * TR
                  for t in np.linspace(5, 10, 6) for c in np.linspace(26, 32, 4)])
    bad_ts = model.dP_dTs(*g.T) >= 0
    model.stats["dP/dTs<0 everywhere"] = not bad_ts.any()
    model.stats["dP/dTs>=0 share of domain"] = float(bad_ts.mean())
    model.stats["dP/dTs>=0 max PLR"] = float(g[bad_ts, 0].max() / (250 * TR)) if bad_ts.any() else None
    model.stats["dP/dTc>0 everywhere"] = bool(np.all(model.dP_dTc(*g.T) > 0))
    return model


# ------------------------------------------------------------------- coil
@dataclass
class CoilModel:
    C_a0: float      # design air capacity rate kW/K
    C_w0: float      # design water capacity rate kW/K
    UA0: float = 0.0  # kW/K, calibrated
    air_frac: float = 0.7   # share of thermal resistance on the air side

    def ua(self, fa, fw):
        return self.UA0 / (self.air_frac / fa ** 0.8 + (1 - self.air_frac) / fw ** 0.8)

    def capacity(self, Ts, T_air_in, fa, fw):
        """Max sensible duty (kW) - dry-coil ε-NTU, conservative for a wet coil."""
        Ca, Cw = self.C_a0 * fa, self.C_w0 * fw
        cmin, cmax = min(Ca, Cw), max(Ca, Cw)
        cr = cmin / cmax
        ntu = self.ua(fa, fw) / cmin
        if abs(1 - cr) < 1e-9:
            eps = ntu / (1 + ntu)
        else:
            e = math.exp(-ntu * (1 - cr))
            eps = (1 - e) / (1 - cr * e)
        return eps * cmin * (T_air_in - Ts)

    def calibrate(self, Q_design, Ts, T_air_in, margin):
        """Pick UA0 so the coil delivers margin × Q_design at design flows."""
        lo, hi = 1.0, 5000.0
        target = Q_design * margin
        for _ in range(80):
            self.UA0 = (lo + hi) / 2
            if self.capacity(Ts, T_air_in, 1.0, 1.0) < target:
                lo = self.UA0
            else:
                hi = self.UA0
        return self.UA0


# ----------------------------------------------------- pumps, fans, tower
@dataclass
class VariableSpeed:
    P0: float          # kW at design flow
    c: float           # fixed-pressure fraction (setpoint / static)

    def power(self, f):
        return self.P0 * f * (self.c + (1 - self.c) * f * f)


@dataclass
class Tower:
    P0: float          # fan kW at full speed
    A0: float          # approach (K) at design heat rejection, full speed
    Qrej0: float

    def approach(self, Qrej, ft):
        return self.A0 * (Qrej / self.Qrej0) * ft ** -0.6

    def power(self, ft):
        return self.P0 * ft ** 3
