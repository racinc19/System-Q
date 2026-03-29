"""
12 polar 'speaker-style' blobs for Fusion 360 decals — 1.75\" x 1.5\" @ 300 DPI.
Physical: 1.75 in x 1.5 in -> 525 x 450 px @ 300 DPI.
Some channels are nearly empty (no signal).
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# 1.75" x 1.5" @ 300 DPI
W_PX, H_PX = 525, 450
DPI = 300
OUT_DIR = Path(__file__).resolve().parent / "fusion_polar_1p75x1p5"


def smooth_blob(theta: np.ndarray, seed: int, roundness: float) -> np.ndarray:
    """Irregular but round-ish polar radius; roundness 0..1 pushes toward circle."""
    rng = np.random.default_rng(seed)
    # Few harmonics — smoother = rounder
    k = 4 + seed % 5
    r = np.ones_like(theta) * 0.35
    for j in range(1, k):
        amp = rng.uniform(0.04, 0.18) * (1.0 - roundness * 0.7)
        phase = rng.uniform(0, 2 * math.pi)
        r += amp * np.sin(j * theta + phase)
    r += roundness * 0.25 * (1 + 0.15 * np.cos(2 * theta))
    r = np.clip(r, 0.08, 1.0)
    return r


def empty_blob(theta: np.ndarray) -> np.ndarray:
    """Nearly flat — 'nothing there'."""
    return np.full_like(theta, 0.12) + 0.02 * np.sin(3 * theta)


def plot_channel(ch: int, out_path: Path) -> None:
    theta = np.linspace(0, 2 * np.pi, 360, endpoint=False)
    # Channels 4, 9, 11 = empty-ish (tweak indices as you like)
    if ch in (4, 9, 11):
        r = empty_blob(theta)
        cmap = "gray"
        title = f"CH {ch:02d} (idle)"
    else:
        roundness = 0.35 + (ch % 5) * 0.1  # vary how round
        r = smooth_blob(theta, seed=100 + ch * 17, roundness=roundness)
        cmap = "inferno"

    fig = plt.figure(figsize=(W_PX / DPI, H_PX / DPI), dpi=DPI)
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_offset(math.pi / 2)
    ax.set_theta_direction(-1)
    theta_closed = np.append(theta, theta[0])
    r_closed = np.append(r, r[0])
    ax.fill(theta_closed, r_closed, alpha=0.85)
    ax.plot(theta_closed, r_closed, color="white", linewidth=0.8, alpha=0.6)
    ax.set_ylim(0, 1.05)
    ax.set_yticklabels([])
    ax.set_xticklabels([])
    ax.grid(False)
    ax.spines["polar"].set_visible(False)
    fig.patch.set_facecolor("#0a0e14")
    ax.set_facecolor("#0a0e14")
    plt.tight_layout(pad=0)
    fig.savefig(out_path, dpi=DPI, facecolor="#0a0e14", edgecolor="none", pad_inches=0)
    plt.close(fig)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ch in range(1, 13):
        out = OUT_DIR / f"polar_ch{ch:02d}_1p75x1p5in_300dpi.png"
        plot_channel(ch, out)
        print(out.name)


if __name__ == "__main__":
    main()
