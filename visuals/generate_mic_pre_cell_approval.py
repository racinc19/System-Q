"""
Single CH01 approval: irregular polar balloon (NOT a perfect circle) + Gate (perfect circle only)
+ three distinct knob treatments: 48V (green + tick), HPF (amber + freq ticks), Ø (cool minimal).
525 x 450 @ 300 DPI for Fusion decal sizing.
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib.pyplot as plt
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

    ax_k = fig.add_axes([0.06, 0.04, 0.88, 0.14])
    ax_k.set_xlim(0, 1)
    ax_k.set_ylim(0, 1)
    ax_k.axis("off")
    ax_k.set_facecolor("#070a0f")

    positions = [0.17, 0.5, 0.83]
    labels = ["48V", "HPF", "Ø"]
    styles = [
        {"edge": "#4ade80", "face": "#14532d"},
        {"edge": "#fbbf24", "face": "#422006"},
        {"edge": "#94a3b8", "face": "#1e293b"},
    ]

    for x, lab, st in zip(positions, labels, styles):
        circ = plt.Circle((x, 0.5), 0.12, facecolor=st["face"], edgecolor=st["edge"], linewidth=2.2)
        ax_k.add_patch(circ)
        ax_k.text(x, 0.5, lab, ha="center", va="center", color="#f1f5f9", fontsize=9, fontweight="bold")
        # Tick marks — 48V few, HPF more (freq steps feel), Ø minimal
        n_ticks = 4 if lab == "48V" else (12 if lab == "HPF" else 0)
        for k in range(n_ticks):
            ang = 2 * math.pi * k / n_ticks
            r1, r2 = 0.085, 0.12
            ax_k.plot(
                [x + r1 * math.cos(ang), x + r2 * math.cos(ang)],
                [0.5 + r1 * math.sin(ang), 0.5 + r2 * math.sin(ang)],
                color=st["edge"],
                lw=0.85,
                alpha=0.75,
            )

    fig.savefig(OUT, dpi=DPI, facecolor="#070a0f", edgecolor="none", pad_inches=0.05)
    plt.close()
    print(OUT)


if __name__ == "__main__":
    main()
