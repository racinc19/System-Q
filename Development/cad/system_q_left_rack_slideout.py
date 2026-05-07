"""
System Q — LEFT RACK concept with slide-out rear panel and side cable routing.

Features:
  - Main shell (front open)
  - Side rails for a sliding rear panel
  - Removable rear panel with pull handle and captive screw holes
  - Side cable channels (left/right)
  - Cable tie tabs along both side walls

Exports:
  - system_q_left_rack_slideout.step
"""
from __future__ import annotations

import sys
from pathlib import Path

import cadquery as cq

# Core envelope (mm)
W = 495.3
H = 266.7
D = 304.8
T = 3.0

# Slide panel and rails
PANEL_T = 2.5
PANEL_INSET = 8.0  # panel sits inside the back opening
RAIL_W = 10.0
RAIL_H = 8.0

# Side cable channels
CHANNEL_W = 22.0
CHANNEL_DEPTH = 14.0
TAB_W = 8.0
TAB_H = 3.0
TAB_D = 6.0


def build_shell() -> cq.Workplane:
    bottom = cq.Workplane("XY").box(W, D, T, centered=(True, True, False)).translate((0, 0, T / 2))
    top = cq.Workplane("XY").box(W, D, T, centered=(True, True, False)).translate((0, 0, H - T / 2))
    left = cq.Workplane("XY").box(T, D, H, centered=(True, True, True)).translate((-W / 2 + T / 2, 0, H / 2))
    right = cq.Workplane("XY").box(T, D, H, centered=(True, True, True)).translate((W / 2 - T / 2, 0, H / 2))
    back_frame = cq.Workplane("XY").box(W, T, H, centered=(True, True, True)).translate((0, D / 2 - T / 2, H / 2))
    return bottom.union(top).union(left).union(right).union(back_frame)


def build_side_rails() -> cq.Workplane:
    # Rails run vertically near back interior, one pair on each side.
    y = D / 2 - T - PANEL_INSET
    z_mid = H / 2
    x_left = -W / 2 + T + CHANNEL_W + RAIL_W / 2 + 2.0
    x_right = W / 2 - T - CHANNEL_W - RAIL_W / 2 - 2.0

    rail_l = cq.Workplane("XY").box(RAIL_W, RAIL_H, H - 30.0, centered=(True, True, True)).translate((x_left, y, z_mid))
    rail_r = cq.Workplane("XY").box(RAIL_W, RAIL_H, H - 30.0, centered=(True, True, True)).translate((x_right, y, z_mid))
    return rail_l.union(rail_r)


def build_slide_panel() -> cq.Workplane:
    panel_w = W - 2 * (T + 2.0)
    panel_h = H - 2 * (T + 2.0)
    y = D / 2 - T - PANEL_INSET

    panel = cq.Workplane("XY").box(panel_w, PANEL_T, panel_h, centered=(True, True, True)).translate((0, y, H / 2))

    # Pull handle
    handle = (
        cq.Workplane("XY")
        .box(70.0, 8.0, 16.0, centered=(True, True, True))
        .translate((0, y - 7.0, H * 0.55))
    )
    panel = panel.union(handle)

    # Captive screw through-holes (top and bottom center)
    for z in (H * 0.82, H * 0.18):
        hole = cq.Workplane("XZ").workplane(offset=y).center(0, z).circle(2.2).extrude(PANEL_T + 12.0)
        panel = panel.cut(hole)

    return panel


def build_cable_channels() -> cq.Workplane:
    # Side channel guide blocks to reserve cable routing paths.
    z_mid = H / 2
    y_mid = 0.0
    x_left = -W / 2 + T + CHANNEL_W / 2
    x_right = W / 2 - T - CHANNEL_W / 2

    left_channel = cq.Workplane("XY").box(CHANNEL_W, D - 20.0, CHANNEL_DEPTH, centered=(True, True, True)).translate(
        (x_left, y_mid, z_mid - 70.0)
    )
    right_channel = cq.Workplane("XY").box(CHANNEL_W, D - 20.0, CHANNEL_DEPTH, centered=(True, True, True)).translate(
        (x_right, y_mid, z_mid - 70.0)
    )
    return left_channel.union(right_channel)


def build_tie_tabs() -> cq.Workplane:
    y_positions = [-D * 0.32, -D * 0.16, 0.0, D * 0.16, D * 0.32]
    z_positions = [H * 0.22, H * 0.44, H * 0.66]
    x_left = -W / 2 + T + CHANNEL_W + TAB_D / 2 + 1.0
    x_right = W / 2 - T - CHANNEL_W - TAB_D / 2 - 1.0
    model = None

    for x in (x_left, x_right):
        for y in y_positions:
            for z in z_positions:
                tab = cq.Workplane("XY").box(TAB_D, TAB_W, TAB_H, centered=(True, True, True)).translate((x, y, z))
                # zip-tie slot through tab
                slot = (
                    cq.Workplane("XY")
                    .box(TAB_D + 1.0, 3.0, 1.2, centered=(True, True, True))
                    .translate((x, y, z))
                )
                tab = tab.cut(slot)
                model = tab if model is None else model.union(tab)

    return model


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "system_q_left_rack_slideout.step"

    shell = build_shell()
    rails = build_side_rails()
    panel = build_slide_panel()
    channels = build_cable_channels()
    tabs = build_tie_tabs()

    assembly = shell.union(rails).union(panel).union(channels).union(tabs)
    cq.exporters.export(assembly, str(out))
    print(f"Exported: {out}")


if __name__ == "__main__":
    main()
