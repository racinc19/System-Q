"""
Generate simplified STEP envelopes for recommended RIGHT-rack power parts.

Parts modeled (bounding-envelope style):
  - Corsair RM750e ATX PSU
  - Mean Well LRS-100-24 AC/DC PSU
  - Traco TEN 40-2415N isolated DC/DC module
  - Dual TEN40 module carrier block (2 modules side-by-side)
"""
from __future__ import annotations

from pathlib import Path

import cadquery as cq


def add_corner_holes(body: cq.Workplane, x_pitch: float, y_pitch: float, hole_d: float, z0: float, zt: float) -> cq.Workplane:
    r = hole_d / 2.0
    for sx in (-0.5, 0.5):
        for sy in (-0.5, 0.5):
            x = sx * x_pitch
            y = sy * y_pitch
            h = cq.Workplane("XY").center(x, y).circle(r).extrude(zt).translate((0, 0, z0))
            body = body.cut(h)
    return body


def corsair_rm750e() -> cq.Workplane:
    # RM750e: 140 (L) x 150 (W) x 86 (H) mm
    # Modeled with X=150, Y=140, Z=86 for rack-placement convenience.
    body = cq.Workplane("XY").box(150.0, 140.0, 86.0, centered=(True, True, False)).translate((0, 0, 43.0))
    # Generic ATX mounting pattern placeholder on one side.
    return add_corner_holes(body, x_pitch=81.5, y_pitch=70.0, hole_d=4.2, z0=5.0, zt=90.0)


def meanwell_lrs100_24() -> cq.Workplane:
    # LRS-100-24: 129 x 97 x 30 mm
    body = cq.Workplane("XY").box(129.0, 97.0, 30.0, centered=(True, True, False)).translate((0, 0, 15.0))
    return add_corner_holes(body, x_pitch=118.0, y_pitch=86.0, hole_d=3.5, z0=3.0, zt=34.0)


def traco_ten40_2415n() -> cq.Workplane:
    # TEN 40 package: 2.0 x 1.0 x 0.4 in = 50.8 x 25.4 x 10.16 mm
    return cq.Workplane("XY").box(50.8, 25.4, 10.16, centered=(True, True, False)).translate((0, 0, 5.08))


def ten40_dual_block(spacing: float = 8.0) -> cq.Workplane:
    a = traco_ten40_2415n().translate((-(25.4 + spacing / 2.0), 0, 0))
    b = traco_ten40_2415n().translate(((25.4 + spacing / 2.0), 0, 0))
    base_w = 2 * 50.8 + spacing + 12.0
    base = cq.Workplane("XY").box(base_w, 40.0, 2.5, centered=(True, True, False)).translate((0, 0, 1.25))
    return base.union(a).union(b)


def main() -> None:
    root = Path(__file__).resolve().parent
    models = {
        "psu_corsair_rm750e.step": corsair_rm750e(),
        "psu_meanwell_lrs100_24.step": meanwell_lrs100_24(),
        "dcdc_traco_ten40_2415n.step": traco_ten40_2415n(),
        "dcdc_traco_ten40_2415n_dual.step": ten40_dual_block(),
    }
    for name, model in models.items():
        out = root / name
        cq.exporters.export(model, str(out))
        print(f"Exported: {out}")


if __name__ == "__main__":
    main()
