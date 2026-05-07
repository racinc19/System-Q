"""
Generate simplified 5-pin XLR connector STEP models (male and female).

Outputs:
  - xlr5_male_panel.step
  - xlr5_female_panel.step
"""
from __future__ import annotations

from pathlib import Path
import math

import cadquery as cq

# Simplified layout dimensions (mm)
FLANGE_D = 26.0
FLANGE_T = 2.2
BARREL_D = 19.0
BARREL_L = 22.0
PIN_RING_R = 4.0
PIN_D = 1.6
PIN_L = 8.0


def base_shell() -> cq.Workplane:
    flange = cq.Workplane("XY").circle(FLANGE_D / 2).extrude(FLANGE_T)
    barrel = (
        cq.Workplane("XY")
        .circle(BARREL_D / 2)
        .extrude(BARREL_L)
        .translate((0, 0, FLANGE_T))
    )
    shell = flange.union(barrel)

    # two panel screw holes (generic)
    for x in (-10.0, 10.0):
        hole = cq.Workplane("XY").center(x, 0).circle(1.8).extrude(FLANGE_T + 1.0)
        shell = shell.cut(hole)
    return shell


def pin_positions() -> list[tuple[float, float]]:
    # 5-pin arc pattern plus center-ish pin for quick layout model
    pts = []
    for i, deg in enumerate((-50, -25, 0, 25, 50)):
        r = PIN_RING_R if i != 2 else PIN_RING_R * 0.6
        pts.append((r * math.cos(math.radians(deg)), r * math.sin(math.radians(deg))))
    return pts


def make_male() -> cq.Workplane:
    model = base_shell()
    z0 = FLANGE_T + 2.0
    for x, y in pin_positions():
        pin = cq.Workplane("XY").center(x, y).circle(PIN_D / 2).extrude(PIN_L).translate((0, 0, z0))
        model = model.union(pin)
    return model


def make_female() -> cq.Workplane:
    model = base_shell()
    z0 = FLANGE_T + 2.0
    # Cut socket cavities instead of protruding pins
    for x, y in pin_positions():
        sock = cq.Workplane("XY").center(x, y).circle((PIN_D / 2) + 0.45).extrude(PIN_L).translate((0, 0, z0))
        model = model.cut(sock)
    # Front mouth recess
    mouth = cq.Workplane("XY").circle(8.2).extrude(3.0).translate((0, 0, FLANGE_T + 0.5))
    model = model.cut(mouth)
    return model


def main() -> None:
    root = Path(__file__).resolve().parent
    male_out = root / "xlr5_male_panel.step"
    female_out = root / "xlr5_female_panel.step"

    cq.exporters.export(make_male(), str(male_out))
    cq.exporters.export(make_female(), str(female_out))
    print(f"Exported: {male_out}")
    print(f"Exported: {female_out}")


if __name__ == "__main__":
    main()
