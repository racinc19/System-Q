Recording Environment
=======================
Personal recording / studio project workspace.

Started: 2026-03-27

(Add session notes, gear list, or folder layout here as you go.)

HTML — spec + BOM (not at repo root)
------------------------------------
- html\SPEC_BOM_LEFT.html
- html\SPEC_BOM_RIGHT.html
- html\VISUAL_CUBE_ENTRY_LEVEL.html — cube entry line (USB cubes → knob / soft fader / transport)
- html\SPEC_BOM_CUBE_ENTRY.html — cube entry BOM; GRACE_PITCH\CUBE_ENTRY_BOM_PRICING.xlsx
- html\LEFT_UNIT_CANVAS.html — left panel layout canvas (12 → 2, bus, phones)
- See html\README.txt

Visuals — decals / generators
-------------------------------
- visuals\  (PNG outputs, mic_pre Python, full console build)

Root raster — Fusion canvas (your art, flat PNG)
-------------------------------------------------
- LEFT_UNIT_CANVAS.png — YOUR image, 1:1 pixels, for Insert → Canvas in Fusion (scale/calibrate there). Replace by copying your exported PNG over this file; do not use the script below for this filename.
- REF_RIGHT_UNIT_HARDWARE.png — optional right-unit photo reference
- LEFT_UNIT_CANVAS_PLACEHOLDER.png — only if you run: py -3 visuals\mic_pre\generate_left_unit_canvas_png.py (synthetic grid; not your artwork)

CAD — System Q LEFT RACK (prototype shell)
-----------------------------------------
- cad/system_q_left_rack.py  — CadQuery source
- cad/system_q_left_rack.step — exported enclosure (regenerate: py -3 cad/system_q_left_rack.py)
- cad/system_q_left_rack_slideout.py — slide-out rear panel + side cable routing concept
- cad/system_q_left_rack_slideout.step — exported slide-out concept enclosure
- cad/xlr5_male_panel.step, cad/xlr5_female_panel.step — 5-pin XLR transfer connector placeholders
- cad/rj45_panel_jack.step — RJ45 connector placeholder
- pip: py -3 -m pip install -r cad/requirements-cad.txt
