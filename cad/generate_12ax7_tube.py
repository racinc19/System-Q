"""
Generate simplified 12AX7 tube STEP models.

Exports:
  - 12ax7_tube.step (single tube)
  - 12ax7_tube_array_12.step (12 tubes in a row, center spacing configurable)

Usage:
  py -3 generate_12ax7_tube.py
  py -3 generate_12ax7_tube.py 30
"""
from __future__ import annotations

import sys
from pathlib import Path

import cadquery as cq

# Approximate 12AX7 envelope/base dimensions (mm)
ENVELOPE_DIA = 19.0
ENVELOPE_H = 52.0
BASE_DIA = 17.0
BASE_H = 12.0
PIN_DIA = 0.9
PIN_H = 8.0


def build_single_tube() -> cq.Workplane:
    envelope_r = ENVELOPE_DIA / 2.0
    base_r = BASE_DIA / 2.0

    # Glass envelope (simple rounded top profile)
    profile = (
        cq.Workplane("XZ")
        .moveTo(0, BASE_H)
        .lineTo(envelope_r, BASE_H)
        .lineTo(envelope_r, BASE_H + ENVELOPE_H - 4.0)
        .threePointArc((envelope_r * 0.7, BASE_H + ENVELOPE_H), (0, BASE_H + ENVELOPE_H))
        .lineTo(0, BASE_H)
        .close()
    )
    envelope = profile.revolve(360, (0, 0, 0), (0, 1, 0))

    # Base
    base = cq.Workplane("XY").circle(base_r).extrude(BASE_H)

    # 9-pin Noval pattern (8 on ring + 1 center)
    ring_r = 4.6
    pins = cq.Workplane("XY")
    for i in range(8):
        ang = i * 45.0
        px = ring_r * __import__("math").cos(__import__("math").radians(ang))
        py = ring_r * __import__("math").sin(__import__("math").radians(ang))
        pins = pins.union(cq.Workplane("XY").center(px, py).circle(PIN_DIA / 2.0).extrude(-PIN_H))
    pins = pins.union(cq.Workplane("XY").circle(PIN_DIA / 2.0).extrude(-PIN_H))

    return envelope.union(base).union(pins)


def build_tube_array(count: int, spacing: float) -> cq.Workplane:
    model = None
    start_x = -((count - 1) * spacing) / 2.0
    for i in range(count):
        tube = build_single_tube().translate((start_x + i * spacing, 0, 0))
        model = tube if model is None else model.union(tube)
    return model


def main() -> None:
    root = Path(__file__).resolve().parent
    spacing = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0

    single = build_single_tube()
    array12 = build_tube_array(12, spacing)

    single_out = root / "12ax7_tube.step"
    array_out = root / "12ax7_tube_array_12.step"

    cq.exporters.export(single, str(single_out))
    cq.exporters.export(array12, str(array_out))

    print(f"Exported: {single_out}")
    print(f"Exported: {array_out} (spacing={spacing} mm)")


if __name__ == "__main__":
    main()
