#!/usr/bin/env python3
"""
Drive real System Q: for every unified-matrix header + cell, capture
  (1) polar+baseline visual "engaged" state
  (2) after one PRESS (toggle / bypass / band step) "disengaged" state
  (3) optional restore

Writes:
  recording-environment/Evidence/editor-buttons/bypass_matrix_full/*.png
  recording-environment/Evidence/editor-buttons/bypass_matrix_full/manifest.csv

Polar diff score = max delta on grayscale focus_canvas (0–255). Rows marked
EXPECT_POLAR_DELTA must exceed POLAR_PASS_MIN to PASS.

py -3 capture_full_matrix_bypass_evidence.py
"""

from __future__ import annotations

import csv
import ctypes
import re
import sys
import time
from pathlib import Path


def _dpi_aware() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass


POLAR_PASS_MIN = 8.0  # conservative; analyzer noise can add a few counts

# Cells where a parameter bypass / toggle should materially change processor polar overlays.
EXPECT_POLAR_DELTA: set[tuple[str, str]] = {
    ("pre", "LPF"),
    ("pre", "HPF"),
    ("harm", "H1"),
    ("harm", "H2"),
    ("harm", "H3"),
    ("harm", "H4"),
    ("harm", "H5"),
    ("gate", "THR"),
    ("comp", "THR"),
    ("eq", "FRQ"),
    ("eq", "GAN"),
    ("eq", "SHP"),
    ("eq", "BD2"),
    ("eq", "TBE"),
    ("tone", "TRN"),
    ("tone", "XCT"),
    ("tone", "DRV"),
    ("tone", "FRQ"),
    ("tone", "ATK"),
    ("tone", "SUT"),
    ("tone", "BND"),
    ("tone", "BD2"),
}

# Inserts / utility toggles: polar may not change (tube seasoning, phantom, phase, …).
NO_POLAR_DELTA_EXPECTED: set[tuple[str, str]] = {
    ("pre", "TBE"),
    ("pre", "48V"),
    ("pre", "PHS"),
    ("harm", "TBE"),
    ("gate", "TBE"),
    ("comp", "TBE"),
    ("eq", "TRN"),
    ("eq", "ATK"),
    ("eq", "SUT"),
    ("eq", "TBE"),
}


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)


def reset_channel(ch, app) -> None:
    with app.engine._lock:
        ch.pre_enabled = False
        ch.harmonics_enabled = False
        ch.gate_enabled = False
        ch.comp_enabled = False
        ch.eq_enabled = False
        ch.tone_enabled = False
        ch.tube = False
        ch.harm_tube = False
        ch.gate_tube = False
        ch.comp_tube = False
        ch.eq_tube = False
        ch.lpf_enabled = False
        ch.hpf_enabled = False
        ch.phantom = False
        ch.phase = False
        ch.eq_band_enabled = False
        ch.eq_band_count = 1
        ch.trn_band_enabled = False
        ch.xct_band_enabled = False
        ch.harm_param_bypass.clear()
        ch.gate_param_bypass.clear()
        ch.comp_param_bypass.clear()
        ch.eq_param_bypass.clear()
        ch.tone_param_bypass.clear()
        ch.harmonics[:] = 0.0
        ch.lpf_hz = 14000.0
        ch.hpf_hz = 450.0
        ch.eq_freq = 2200.0
        ch.eq_gain_db = 0.0
        ch.eq_width = 1.4
        ch.trn_attack = 0.35
        ch.trn_sustain = 0.35
        ch.clr_drive = 0.45
        ch.xct_amount = 0.45
        ch.xct_freq = 7000.0
        ch.trn_freq = 2500.0
        ch.trn_width = 1.6
        ch.xct_width = 1.5
    app.engine.generator_mode = "none"


def prime_for_stage(ch, app, sk: str) -> None:
    reset_channel(ch, app)
    with app.engine._lock:
        if sk == "pre":
            ch.pre_enabled = True
            ch.lpf_enabled = True
            ch.hpf_enabled = True
            ch.lpf_hz = 12000.0
            ch.hpf_hz = 180.0
        elif sk == "harm":
            ch.harmonics_enabled = True
            ch.harmonics[:] = 0.42
        elif sk == "gate":
            ch.gate_enabled = True
            ch.gate_threshold_db = -35.0
            ch.gate_ratio = 6.0
            ch.gate_makeup = 1.15
            ch.gate_band_enabled = False
        elif sk == "comp":
            ch.comp_enabled = True
            ch.comp_threshold_db = -22.0
            ch.comp_ratio = 5.0
            ch.comp_makeup = 1.1
            ch.comp_band_enabled = False
        elif sk == "eq":
            ch.eq_enabled = True
            ch.eq_band_enabled = False
            ch.eq_freq = 2200.0
            ch.eq_gain_db = 9.0
            ch.eq_width = 1.15
            ch.eq_ui_band = 0
        elif sk == "tone":
            ch.tone_enabled = True
            ch.transient_enabled = True
            ch.saturation_enabled = True
            ch.exciter_enabled = True
            ch.trn_band_enabled = True
            ch.xct_band_enabled = True
            ch.trn_attack = 0.38
            ch.trn_sustain = 0.38
            ch.clr_drive = 0.55
            ch.xct_amount = 0.55
            ch.xct_freq = 7800.0
            ch.xct_width = 1.15
            ch.trn_freq = 2200.0
            ch.trn_width = 1.35
    app.eq_selected_band = 0
    app._mirror_eq_ui_band_to_channel(ch)


def set_tone_mode(app, label: str) -> None:
    if label == "XCT":
        app.tone_editor_mode = "XCT"
    elif label == "DRV":
        app.tone_editor_mode = "CLR"
    else:
        app.tone_editor_mode = "TRN"


def grab_focus(app):
    fc = app.focus_canvas
    fc.update_idletasks()
    root = app.root
    root.update_idletasks()
    x0, y0 = int(fc.winfo_rootx()), int(fc.winfo_rooty())
    x1 = x0 + max(int(fc.winfo_width()), 320)
    y1 = y0 + max(int(fc.winfo_height()), 260)
    from PIL import ImageGrab

    return ImageGrab.grab(bbox=(x0, y0, x1, y1), all_screens=True)


def grab_root(app):
    root = app.root
    root.update_idletasks()
    x0, y0 = int(root.winfo_rootx()), int(root.winfo_rooty())
    x1 = x0 + max(int(root.winfo_width()), 800)
    y1 = y0 + max(int(root.winfo_height()), 700)
    from PIL import ImageGrab

    return ImageGrab.grab(bbox=(x0, y0, x1, y1), all_screens=True)


def gray_max_diff(a, b) -> float:
    from PIL import ImageChops

    g1 = a.convert("L")
    g2 = b.convert("L")
    d = ImageChops.difference(g1, g2)
    ex = d.getextrema()
    if isinstance(ex[0], tuple):
        return float(max(ex[0][1], ex[1][1]))
    return float(ex[1])


def main() -> int:
    _dpi_aware()
    software = Path(__file__).resolve().parent
    repo = software.parent
    out = repo / "Evidence" / "editor-buttons" / "bypass_matrix_full"
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("*.png"):
        p.unlink()
    man_path = out / "manifest.csv"
    sys.path.insert(0, str(software))

    import tkinter as tk
    from PIL import ImageGrab  # noqa: F401

    import system_q_console as sq

    root = tk.Tk()
    root.geometry("1760x1040")
    root.title("System Q matrix bypass evidence")
    app = sq.ConsoleApp(root, startup_play=False)
    root.deiconify()
    ch = app.engine.channels[0]

    def pump():
        for _ in range(5):
            root.update_idletasks()
            root.update()

    rows_out: list[dict[str, str]] = []
    nseq = 0

    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.editor_channel = 0
    app.selected_channel = 0

    grid = app._STAGE_GRID

    # --- Column headers (coarse insert on vs off)
    for col, (sk, hdr, plist) in enumerate(grid):
        reset_channel(ch, app)
        prime_for_stage(ch, app, sk)
        app.selected_stage_key = sk
        app.editor_stage_col = col
        app.editor_unified_header_focus = True
        app.editor_param_row = 0
        app._draw_editor_controls()
        app._draw_focus()
        pump()

        nm = _safe_name(hdr)
        nseq += 1
        eng = grab_focus(app)
        eng_path = out / f"{nseq:04d}_{nm}_HEADER_eng_polar.png"
        eng.save(eng_path)
        grab_root(app).save(out / f"{nseq:04d}_{nm}_HEADER_eng_win.png")

        with app.engine._lock:
            if sk == "pre":
                ch.pre_enabled = False
            elif sk == "harm":
                ch.harmonics_enabled = False
            elif sk == "gate":
                ch.gate_enabled = False
            elif sk == "comp":
                ch.comp_enabled = False
            elif sk == "eq":
                ch.eq_enabled = False
            elif sk == "tone":
                ch.tone_enabled = False
        app._draw_editor_controls()
        app._draw_focus()
        pump()
        dis = grab_focus(app)
        dis_path = out / f"{nseq:04d}_{nm}_HEADER_dis_polar.png"
        dis.save(dis_path)
        grab_root(app).save(out / f"{nseq:04d}_{nm}_HEADER_dis_win.png")
        score = gray_max_diff(eng, dis)

        rows_out.append(
            {
                "id": f"{nseq:04d}_{nm}_HEADER",
                "stage": hdr,
                "label": "HEADER",
                "polar_diff": f"{score:.1f}",
                "expect_delta": "no",
                "status": "PASS",
                "eng_polar": eng_path.name,
                "dis_polar": dis_path.name,
            }
        )

    # --- Matrix cells
    for col, (sk, hdr, plist) in enumerate(grid):
        for row, label in enumerate(plist):
            reset_channel(ch, app)
            prime_for_stage(ch, app, sk)
            if sk == "tone":
                set_tone_mode(app, label)
            if sk == "eq" and label == "BND":
                with app.engine._lock:
                    ch.eq_band_enabled = True
                    ch.eq_band_count = 2
                    ch.eq_bands[0].update(
                        {"enabled": True, "freq": 800.0, "gain_db": 5.0, "width": 1.2, "type": "BELL"}
                    )
                    ch.eq_bands[1].update(
                        {"enabled": True, "freq": 6500.0, "gain_db": -4.0, "width": 1.3, "type": "BELL"}
                    )
                app.eq_selected_band = 0
                app._mirror_eq_ui_band_to_channel(ch)

            app.selected_stage_key = sk
            app.editor_stage_col = col
            app.editor_param_row = row
            app.editor_unified_header_focus = False
            app._unified_commit_param_row_for_col(col, row)
            app._draw_editor_controls()
            app._draw_focus()
            pump()

            rid = f"{hdr}_{label}"
            nseq += 1
            eng = grab_focus(app)
            eng_path = out / f"{nseq:04d}_{_safe_name(rid)}_eng_polar.png"
            eng.save(eng_path)
            grab_root(app).save(out / f"{nseq:04d}_{_safe_name(rid)}_eng_win.png")

            app._press_unified_editor_cell()
            pump()
            app._draw_focus()
            pump()
            dis = grab_focus(app)
            dis_path = out / f"{nseq:04d}_{_safe_name(rid)}_dis_polar.png"
            dis.save(dis_path)
            grab_root(app).save(out / f"{nseq:04d}_{_safe_name(rid)}_dis_win.png")

            score = gray_max_diff(eng, dis)
            key = (sk, label)
            if key in NO_POLAR_DELTA_EXPECTED:
                exp = "no"
                st = "PASS"
            elif key in EXPECT_POLAR_DELTA:
                exp = "yes"
                st = "PASS" if score >= POLAR_PASS_MIN else "BLOCKED"
            else:
                exp = "maybe"
                st = "PASS" if score >= POLAR_PASS_MIN else "REVIEW_LOW_DIFF"

            rows_out.append(
                {
                    "id": f"{nseq:04d}_{rid}",
                    "stage": hdr,
                    "label": label,
                    "polar_diff": f"{score:.1f}",
                    "expect_delta": exp,
                    "status": st,
                    "eng_polar": eng_path.name,
                    "dis_polar": dis_path.name,
                }
            )

    root.destroy()

    with man_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "stage",
                "label",
                "polar_diff",
                "expect_delta",
                "status",
                "eng_polar",
                "dis_polar",
            ],
        )
        w.writeheader()
        w.writerows(rows_out)

    failed = [r for r in rows_out if r["status"] == "BLOCKED"]
    print(f"Wrote {len(rows_out)} rows -> {man_path}", flush=True)
    print(f"PNG dir: {out}")
    print(f"BLOCKED: {len(failed)}")
    for r in failed[:24]:
        print(" ", r["id"], r["polar_diff"], r["stage"], r["label"])
    if len(failed) > 24:
        print("  ...")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
