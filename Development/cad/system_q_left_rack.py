"""
System Q — LEFT RACK main enclosure (CadQuery → STEP)
Dimensions per spec: 495.3 x 266.7 x 304.8 mm (W x H x D), 3 mm Al walls, front open.
"""
from __future__ import annotations

import sys

import cadquery as cq

# --- mm ---
W = 495.3  # 19.5"
H = 266.7  # 6U
D = 304.8  # 12"
T = 3.0  # wall thickness

# XLR / combo: typical panel hole ~22–24 mm; use 11 mm radius
HOLE_R_COMBO = 11.0
# IEC C14 panel cutout (common) ~27 x 47 mm rounded rect — use 48 x 27 center rect
IEC_W, IEC_H = 48.0, 27.0
# USB-B panel ~12 x 11
USB_W, USB_H = 12.0, 11.0
# Multi-pin / umbilical placeholder: D-sub 25 shell ~53 x 17
DSUB_W, DSUB_H = 53.0, 17.0


def main() -> cq.Workplane:
    # Five-sided shell: bottom, top, left, right, back. Front (Y=0 plane) OPEN.
    bottom = cq.Workplane("XY").box(W, D, T, centered=(True, True, False)).translate((0, 0, T / 2))
    top = cq.Workplane("XY").box(W, D, T, centered=(True, True, False)).translate((0, 0, H - T / 2))
    left = cq.Workplane("XY").box(T, D, H, centered=(True, True, True)).translate((-W / 2 + T / 2, 0, H / 2))
    right = cq.Workplane("XY").box(T, D, H, centered=(True, True, True)).translate((W / 2 - T / 2, 0, H / 2))
    back = cq.Workplane("XY").box(W, T, H, centered=(True, True, True)).translate((0, D / 2 - T / 2, H / 2))
    shell = bottom.union(top).union(left).union(right).union(back)

    # 12 combo holes — centers along X, mid height on back face (inside Y = D/2 - T)
    y_back = D / 2 - T / 2
    z_row = H * 0.52
    for i in range(12):
        x = -W / 2 + W * (i + 0.5) / 12
        cyl = (
            cq.Workplane("YZ")
            .workplane(offset=x)
            .center(D / 2 - T / 2, z_row)
            .circle(HOLE_R_COMBO)
            .extrude(T + 4)
        )
        shell = shell.cut(cyl)

    # Rear panel rectangular cutouts (through back wall), placed left→right on outside back face
    # Positions in (x, z) from center origin — back face Y = D/2 - T/2
    def cut_rect_center(cx: float, cz: float, rw: float, rh: float) -> None:
        nonlocal shell
        blk = (
            cq.Workplane("YZ")
            .workplane(offset=cx)
            .center(D / 2 - T / 2, cz)
            .rect(rh, rw)
            .extrude(T + 4)
        )
        shell = shell.cut(blk)

    # IEC (left side of back), USB-B, D-sub umbilical, second hole for "USB to right rack" — group bottom
    z_low = H * 0.18
    cut_rect_center(-W * 0.38, z_low, IEC_W, IEC_H)
    cut_rect_center(-W * 0.22, z_low, USB_W, USB_H)
    cut_rect_center(-W * 0.05, z_low, DSUB_W, DSUB_H)
    # Second small port (USB-B to right rack) — placeholder near center-bottom
    cut_rect_center(W * 0.12, z_low, USB_W, USB_H)

    # Rack ears: 3 mm thick, extend past sides; EIA approximate hole spacing on vertical ear
    ear_w = 20.0
    ear_t = 3.0
    # Left ear plate: x from -W/2-ear_w to -W/2
    ear_l = (
        cq.Workplane("XY")
        .box(ear_w, D, H, centered=(True, True, True))
        .translate((-W / 2 - ear_w / 2, 0, H / 2))
    )
    ear_r = (
        cq.Workplane("XY")
        .box(ear_w, D, H, centered=(True, True, True))
        .translate((W / 2 + ear_w / 2, 0, H / 2))
    )
    shell = shell.union(ear_l).union(ear_r)

    # Rack mounting holes: 6.35 mm dia clearance for 10-32, vertical spacing ~15.875 mm (5/8") x 3
    hole_r = 3.25
    z_start = H * 0.25
    pitch = 15.875
    for z_off in (0, pitch, 2 * pitch):
        z = z_start + z_off
        for ex in (-W / 2 - ear_w / 2, W / 2 + ear_w / 2):
            cyl = (
                cq.Workplane("YZ")
                .workplane(offset=ex)
                .center(D / 2 - ear_t / 2, z)
                .circle(hole_r)
                .extrude(ear_t + 4)
            )
            shell = shell.cut(cyl)

    return shell


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else str(
        __import__("pathlib").Path(__file__).resolve().parent / "system_q_left_rack.step"
    )
    model = main()
    cq.exporters.export(model, out)
    print(f"Exported: {out}")
