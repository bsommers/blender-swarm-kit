#!/usr/bin/env python3
"""
Generalized Multi-View Silhouette Calibration & Height-Aligned Ortho-Plate Builder.

Uses CIE-Lab chromaticity delta against border background strips to separate a subject
from a light studio backdrop while rejecting neutral gray cast shadows, then emits
metric-calibrated RGBA orthographic reference plates for Blender/CAD viewports.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage


def srgb_to_linear(rgb01: np.ndarray) -> np.ndarray:
    arr = np.clip(np.asarray(rgb01, dtype=np.float32), 0.0, 1.0)
    return np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)


def rgb01_to_lab(rgb01: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lin = srgb_to_linear(rgb01)
    m = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ],
        dtype=np.float32,
    )
    xyz = lin @ m.T
    xyz[..., 0] /= 0.95047
    xyz[..., 2] /= 1.08883
    eps = 0.008856
    kappa = 903.3
    f = np.where(xyz > eps, np.cbrt(np.maximum(xyz, 0.0)), (kappa * xyz + 16.0) / 116.0)
    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return L, a, b


def segment_foreground_lab(rgb_u8: np.ndarray, chroma_thresh: float = 9.0, dark_thresh: float = 24.0) -> np.ndarray:
    """Shadow-invariant foreground segmentation using CIE Lab chromaticity delta from border strip."""
    h, w, _ = rgb_u8.shape
    L, a, b = rgb01_to_lab(rgb_u8.astype(np.float32) / 255.0)
    bw = max(8, int(min(h, w) * 0.04))
    border = np.zeros((h, w), dtype=bool)
    border[:bw, :] = border[-bw:, :] = border[:, :bw] = border[:, -bw:] = True

    bL = L[border]
    bright = bL >= np.percentile(bL, 40)
    a_bg = float(np.median(a[border][bright]))
    b_bg = float(np.median(b[border][bright]))

    d_ab = np.hypot(a - a_bg, b - b_bg)
    raw = (d_ab > chroma_thresh) | (L < dark_thresh)

    scale = max(1, int(round(min(h, w) / 450.0)))
    raw = ndimage.binary_opening(raw, structure=np.ones((2 * scale + 1, 2 * scale + 1)))
    raw = ndimage.binary_closing(raw, structure=np.ones((4 * scale + 1, 4 * scale + 1)))
    raw = ndimage.binary_fill_holes(raw)

    labeled, n = ndimage.label(raw)
    if n == 0:
        raise RuntimeError("No foreground region detected")
    sizes = ndimage.sum(raw, labeled, range(1, n + 1))
    mask = labeled == (int(np.argmax(sizes)) + 1)
    return mask


def build_ortho_plate(
    rgb_u8: np.ndarray,
    mask: np.ndarray,
    out_size: tuple[int, int] = (600, 800),
    top_px: int = 58,
    bot_px: int = 742,
) -> tuple[Image.Image, dict[str, Any]]:
    """Height-align a segmented view onto an RGBA orthographic reference plate."""
    ys, xs = np.where(mask)
    y_top, y_bot = int(ys.min()), int(ys.max())
    cx = float(0.5 * (xs.min() + xs.max()))
    h_px = max(1.0, float(y_bot - y_top))
    out_w, out_h = out_size
    scale = (bot_px - top_px) / h_px

    alpha = np.clip(ndimage.gaussian_filter(mask.astype(np.float32), sigma=0.8) * 255.0, 0, 255).astype(np.uint8)
    src = Image.fromarray(np.dstack([rgb_u8, alpha]), mode="RGBA")
    new_w = max(1, int(round(rgb_u8.shape[1] * scale)))
    new_h = max(1, int(round(rgb_u8.shape[0] * scale)))
    resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    paste_x = int(round(out_w / 2.0 - cx * scale))
    paste_y = int(round(top_px - y_top * scale))
    canvas.paste(resized, (paste_x, paste_y), resized)
    meta = {
        "scale": round(scale, 6),
        "src_bbox_y": [y_top, y_bot],
        "src_cx": round(cx, 2),
        "paste": [paste_x, paste_y],
        "ortho_size": [out_w, out_h],
        "height_span_px": bot_px - top_px,
    }
    return canvas, meta


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build height-aligned RGBA ortho reference plates from photos.")
    p.add_argument("images", nargs="+", type=Path, help="Input photo paths")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--target-height-m", type=float, default=0.180)
    p.add_argument("--chroma-thresh", type=float, default=9.0)
    args = p.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"target_height_m": args.target_height_m, "views": {}}
    for img_path in args.images:
        rgb = np.asarray(Image.open(img_path).convert("RGB"))
        mask = segment_foreground_lab(rgb, chroma_thresh=args.chroma_thresh)
        plate, meta = build_ortho_plate(rgb, mask)
        out_file = args.out_dir / f"ortho_{img_path.stem}.png"
        plate.save(out_file)
        summary["views"][img_path.stem] = {"output": str(out_file), **meta}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
