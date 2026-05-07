"""
Generate simplified power-supply STEP models for rack layout.

Outputs:
  - psu_meanwell_lrs150_24.step
  - dcdc_traco_ten40_2415.step
  - phantom_48v_module.step
"""
from __future__ import annotations

from pathlib import Path

import cadquery as cq


def box_with_holes(
    w: float,
    d: float,
    h: float,
    hole_d: float,
    x_pitch: float,
    y_pitch: float,
    z0: float = 0.0,
) -> cq.Workplane:
    body = cq.Workplane("XY").box(w, d, h, centered=(True, True, False)).translate((0, 0, z0 + h / 2))
    r = hole_d / 2.0
    hole_z = z0 + 1.0
    for sx in (-0.5, 0.5):
        for sy in (-0.5, 0.5):
            x = sx * x_pitch
            y = sy * y_pitch
            hole = cq.Workplane("XY").center(x, y).circle(r).extrude(h + 2.0).translate((0, 0, hole_z))
            body = body.cut(hole)
    return body


def meanwell_lrs150_24() -> cq.Workplane:
    # Typical datasheet envelope: 159 x 97 x 30 mm.
    # Hole pattern here is simplified for placement planning.
    return box_with_holes(w=159.0, d=97.0, h=30.0, hole_d=3.5, x_pitch=140.0, y_pitch=78.0)


def traco_ten40_2415() -> cq.Workplane:
    # Typical module body: 50.8 x 25.4 x ~10.2 mm (2.0" x 1.0" package)
    return box_with_holes(w=50.8, d=25.4, h=10.2, hole_d=2.8, x_pitch=40.0, y_pitch=15.0)


def phantom_48v_module() -> cq.Workplane:
    # Generic compact module placeholder for board-space planning.
    return box_with_holes(w=70.0, d=35.0, h=20.0, hole_d=3.0, x_pitch=58.0, y_pitch=23.0)


def main() -> None:
    root = Path(__file__).resolve().parent
    models = {
        "psu_meanwell_lrs150_24.step": meanwell_lrs150_24(),
        "dcdc_traco_ten40_2415.step": traco_ten40_2415(),
        "phantom_48v_module.step": phantom_48v_module(),
    }
    for name, model in models.items():
        out = root / name
        cq.exporters.export(model, str(out))
        print(f"Exported: {out}")


if __name__ == "__main__":
    main()
