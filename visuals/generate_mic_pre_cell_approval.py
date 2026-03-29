"""
Single CH01 approval: irregular polar + Gate + flat face-on indicators (no perspective knobs).
- 48 VOLT: red text = ON
- HPF: green shelf curve (high-pass shelf graphic)
- Phase: yellow Ø (circle with slash), face-on
525 x 450 @ 300 DPI for Fusion decal sizing.
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

W_PX, H_PX = 525, 450
DPI = 300
OUT = Path(__file__).resolve().parent / "mic_pre_cell_APPROVAL_ch01.png"

N = 720
theta = np.linspace(0, 2 * np.pi, N, endpoint=False)
rng = np.random.default_rng(42)
# Irregular speaker-style balloon — always NOT a perfect circle
r = (
    0.44
    + 0.11 * np.sin(3 * theta + 0.3)
    + 0.07 * np.sin(7 * theta + 0.8)
    + 0.05 * np.cos(5 * theta) * np.sin(2 * theta)
    + 0.03 * rng.standard_normal(N)
)
r = np.clip(r, 0.2, 0.94)
theta_c = np.append(theta, theta[0])
r_c = np.append(r, r[0])


def main() -> None:
    fig = plt.figure(figsize=(W_PX / DPI, H_PX / DPI), dpi=DPI)
    ax = fig.add_axes([0, 0.22, 1, 0.78], projection="polar")
    ax.set_theta_offset(math.pi / 2)
    ax.set_theta_direction(-1)

    # Heat: map radius to color (hot outside, cool inside) — single clean fill, no radial spokes
    t_mesh = np.linspace(0, 2 * np.pi, 200)
    r_mesh = np.linspace(0, 1, 80)
    T, R = np.meshgrid(t_mesh, r_mesh)
    # Interpolate boundary r at each angle for inside/outside mask
    r_b = np.interp(t_mesh, theta, r, period=2 * math.pi)
    Z = np.zeros_like(R)
    for j, rr in enumerate(r_mesh):
        Z[j, :] = np.where(rr <= r_b, rr / (r_b + 0.02), np.nan)

    pcm = ax.pcolormesh(
        T,
        R,
        Z,
        cmap="inferno",
        shading="auto",
        alpha=0.88,
    )
    pcm.set_clim(0, 1)

    # Mic pre "closing down": RED in the annulus between Gate (inside) and outer polar edge.
    # Outer rim of the polarity graph = red (was white) — shows energy to tame.
    gate_r = 0.50  # tighter = more "closed down" vs typical blob max ~0.9x
    ax.fill_between(
        theta,
        gate_r,
        r,
        where=(r > gate_r),
        color="#dc2626",
        alpha=0.62,
        interpolate=True,
    )
    ax.plot(theta_c, r_c, color="#b91c1c", linewidth=2.8, alpha=0.95, solid_capstyle="round")

    # GATE — perfect circle; smaller so it visually closes off / contains the red ring
    tg = np.linspace(0, 2 * np.pi, 720)
    ax.plot(tg, np.full_like(tg, gate_r), color="#22d3ee", linewidth=2.8, alpha=0.98)

    ax.set_ylim(0, 1.0)
    ax.set_yticklabels([])
    ax.set_xticklabels([])
    ax.grid(False)
    ax.spines["polar"].set_visible(False)
    fig.patch.set_facecolor("#070a0f")
    ax.set_facecolor("#070a0f")

    # Bottom strip: all face-on — no rotary knobs; flat icons + text
    ax_k = fig.add_axes([0.04, 0.02, 0.92, 0.16])
    ax_k.set_xlim(0, 1)
    ax_k.set_ylim(0, 1)
    ax_k.axis("off")
    ax_k.set_facecolor("#070a0f")

    # 1) 48 VOLT — red = ON (face-on typography)
    ax_k.text(
        0.17,
        0.58,
        "48 VOLT",
        ha="center",
        va="center",
        color="#ef4444",
        fontsize=13,
        fontweight="bold",
    )
    ax_k.text(0.17, 0.22, "ON", ha="center", va="center", color="#ef4444", fontsize=9, alpha=0.9)

    # 2) HPF — green shelf response (low freqs down, highs flat), face-on plot in center column
    t = np.linspace(0, 1, 48)
    # Shelf: low attenuation on left (low freq), rises to unity on right — classic HPF magnitude sketch
    resp = np.empty_like(t, dtype=float)
    m = t < 0.22
    resp[m] = 0.08 + 0.1 * (t[m] / 0.22)
    resp[~m] = 0.18 + 0.82 * ((t[~m] - 0.22) / (1 - 0.22)) ** 0.85
    resp = np.clip(resp, 0, 1)
    x_line = 0.36 + t * 0.28
    y_line = 0.18 + resp * 0.68
    ax_k.plot(x_line, y_line, color="#22c55e", linewidth=2.8, solid_capstyle="round")
    ax_k.plot([0.36, 0.64], [0.18, 0.18], color="#14532d", linewidth=1.0, alpha=0.5)
    ax_k.text(0.5, 0.92, "HPF", ha="center", va="top", color="#22c55e", fontsize=9, fontweight="bold")

    # 3) Phase — yellow circle with diagonal (polarity invert), face-on
    cx, cy, rad = 0.83, 0.48, 0.095
    circ = mpatches.Circle(
        (cx, cy),
        rad,
        fill=False,
        edgecolor="#eab308",
        linewidth=2.6,
    )
    ax_k.add_patch(circ)
    ax_k.plot(
        [cx - rad * 0.72, cx + rad * 0.72],
        [cy + rad * 0.72, cy - rad * 0.72],
        color="#eab308",
        linewidth=2.4,
        solid_capstyle="round",
    )
    ax_k.text(cx, 0.1, "PHASE", ha="center", va="bottom", color="#eab308", fontsize=8, fontweight="bold")

    fig.savefig(OUT, dpi=DPI, facecolor="#070a0f", edgecolor="none", pad_inches=0.05)
    plt.close()
    print(OUT)


if __name__ == "__main__":
    main()
