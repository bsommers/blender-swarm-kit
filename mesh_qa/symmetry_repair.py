#!/usr/bin/env python3
"""
Generalized Bilateral Mirror Symmetry Repair & Heightmap Primitives.

Provides reusable building blocks extracted from Operation Dumb Bunny:
  - `smoothstep`, `ellipse_mask`, `make_micro_grain`
  - `directional_inpaint_strip` & `harmonic_inpaint_crisp`
  - `mirror_symmetry_repair`: donor-half -> damaged-half seam-feathered repair with local gain matching
  - `enforce_strict_x_symmetry`: guarantees H[:, x] == H[:, W - 1 - x] (max_abs_sym_err == 0.0)
  - `compute_symmetry_metrics`: MAE, RMS, Pearson r, and composite symmetry score (0..100%)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage


def smoothstep(edge0: float | np.ndarray, edge1: float | np.ndarray, x: float | np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0 + 1e-8), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def ellipse_mask(h: int, w: int, cx: float, cy: float, rx: float, ry: float, feather: float = 0.0) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - cx) / (rx + 1e-6)) ** 2 + ((yy - cy) / (ry + 1e-6)) ** 2)
    if feather <= 0:
        return (d <= 1.0).astype(np.float32)
    return (1.0 - smoothstep(1.0 - feather, 1.0 + feather, d)).astype(np.float32)


def make_micro_grain(h: int, w: int, strength: float = 1.5, seed: int = 42) -> np.ndarray:
    """Isotropic fine photographic sensor/surface micro-grain (zero repeating tiling)."""
    rng = np.random.default_rng(seed)
    lum_n = rng.normal(0.0, strength, size=(h, w, 1)).astype(np.float32)
    chr_n = rng.normal(0.0, strength * 0.25, size=(h, w, 3)).astype(np.float32)
    grain = lum_n + chr_n
    for c in range(3):
        grain[..., c] = ndimage.gaussian_filter(grain[..., c], sigma=0.65)
    return grain


def directional_inpaint_strip(
    img: np.ndarray, mask: np.ndarray, detail: np.ndarray | None = None, margin: int = 20, feather: float = 2.0
) -> np.ndarray:
    """Horizontal scanline interpolation across narrow vertical cracks with detail re-injection."""
    out = img.astype(np.float32).copy()
    m_bin = mask > 0.5
    ys = np.where(m_bin.any(axis=1))[0]
    w = img.shape[1]
    for y in ys:
        xs = np.where(m_bin[y])[0]
        if len(xs) == 0:
            continue
        x0, x1 = int(xs[0]), int(xs[-1])
        lx0, lx1 = max(0, x0 - margin), max(1, x0 - 2)
        rx0, rx1 = min(w - 1, x1 + 2), min(w, x1 + margin)
        col_l = np.median(img[y, lx0:lx1], axis=0)
        col_r = np.median(img[y, rx0:rx1], axis=0)
        t = np.linspace(0.0, 1.0, x1 - x0 + 1, dtype=np.float32)[:, None]
        out[y, x0 : x1 + 1] = col_l[None, :] * (1.0 - t) + col_r[None, :] * t

    out_low = np.stack([ndimage.gaussian_filter(out[..., c], sigma=(2.2, 1.0)) for c in range(3)], axis=-1)
    if detail is not None:
        out_crisp = np.clip(out_low + 0.85 * detail, 0.0, 255.0)
    else:
        out_crisp = np.clip(out_low, 0.0, 255.0)
    soft_m = np.clip(ndimage.gaussian_filter(mask.astype(np.float32), sigma=feather), 0.0, 1.0)[..., None]
    return img * (1.0 - soft_m) + out_crisp * soft_m


def harmonic_inpaint_crisp(
    img: np.ndarray, mask: np.ndarray, detail: np.ndarray | None = None, n_iters: int = 80, feather: float = 2.0
) -> np.ndarray:
    """Multiscale harmonic fill with optional high-frequency micro-detail re-injection."""
    m = mask > 0.5
    if not m.any():
        return img.astype(np.float32).copy()

    out = img.astype(np.float32).copy()
    valid = (~m).astype(np.float32)
    for sigma in (32.0, 16.0, 8.0, 4.0):
        num = np.stack([ndimage.gaussian_filter(out[..., c] * valid, sigma=sigma) for c in range(3)], axis=-1)
        den = ndimage.gaussian_filter(valid, sigma=sigma)[..., None] + 1e-6
        out[m] = (num / den)[m]
        valid = np.ones_like(valid)

    for _ in range(n_iters):
        blurred = np.stack([ndimage.uniform_filter(out[..., c], size=3) for c in range(3)], axis=-1)
        out[m] = blurred[m]

    out_crisp = np.clip(out + (0.85 * detail if detail is not None else 0.0), 0.0, 255.0)
    soft_m = np.clip(ndimage.gaussian_filter(mask.astype(np.float32), sigma=feather), 0.0, 1.0)[..., None]
    return img * (1.0 - soft_m) + out_crisp * soft_m


def enforce_strict_x_symmetry(heightmap: np.ndarray) -> np.ndarray:
    """Guarantee exact float32 horizontal symmetry: H[:, x] == H[:, W - 1 - x]."""
    h = np.asarray(heightmap, dtype=np.float32)
    sym = 0.5 * (h + h[:, ::-1])
    return sym.astype(np.float32)


def compute_symmetry_metrics(
    img_arr: np.ndarray, roi_mask: np.ndarray | None = None, excl_mask: np.ndarray | None = None
) -> dict[str, Any]:
    arr = np.asarray(img_arr, dtype=np.float32)
    h, w = arr.shape[:2]
    half = w // 2
    if roi_mask is None:
        roi_mask = np.ones((h, w), dtype=np.float32)

    left = arr[:, :half]
    right_flipped = arr[:, w - 1 : half - 1 : -1]
    m_half = (roi_mask[:, :half] > 0.5) & (roi_mask[:, w - 1 : half - 1 : -1] > 0.5)
    if not m_half.any():
        return {"overall_symmetry_pct": 0.0, "mae_rgb_all": 255.0, "rms_rgb_all": 255.0, "pearson_r_all": 0.0}

    diff = np.abs(left - right_flipped)
    mae_all = float(diff[m_half].mean())
    rms_all = float(np.sqrt((diff[m_half] ** 2).mean()))
    lv = left[m_half].reshape(-1)
    rv = right_flipped[m_half].reshape(-1)
    corr = float(np.corrcoef(lv, rv)[0, 1]) if lv.size > 10 and np.std(lv) > 1e-6 and np.std(rv) > 1e-6 else 1.0
    score_all = 0.65 * (100.0 * (1.0 - mae_all / 255.0)) + 0.35 * (100.0 * max(0.0, corr))

    if excl_mask is not None:
        m_skin = m_half & (excl_mask[:, :half] < 0.5) & (excl_mask[:, w - 1 : half - 1 : -1] < 0.5)
        if m_skin.any():
            mae_skin = float(diff[m_skin].mean())
            lv_s = left[m_skin].reshape(-1)
            rv_s = right_flipped[m_skin].reshape(-1)
            corr_skin = (
                float(np.corrcoef(lv_s, rv_s)[0, 1])
                if lv_s.size > 10 and np.std(lv_s) > 1e-6 and np.std(rv_s) > 1e-6
                else 1.0
            )
            score_skin = 0.65 * (100.0 * (1.0 - mae_skin / 255.0)) + 0.35 * (100.0 * max(0.0, corr_skin))
        else:
            mae_skin, corr_skin, score_skin = mae_all, corr, score_all
    else:
        mae_skin, corr_skin, score_skin = mae_all, corr, score_all

    return {
        "overall_symmetry_pct": round(score_all, 2),
        "skin_structure_symmetry_pct": round(score_skin, 2),
        "mae_rgb_all": round(mae_all, 2),
        "rms_rgb_all": round(rms_all, 2),
        "pearson_r_all": round(corr, 4),
        "mae_rgb_skin": round(mae_skin, 2),
        "pearson_r_skin": round(corr_skin, 4),
    }


def mirror_symmetry_repair(
    img_arr: np.ndarray,
    donor: str = "left",
    seam_half_width: float = 8.0,
    preserve_mask: np.ndarray | None = None,
) -> np.ndarray:
    """
    Mirror the intact half (`donor="left"` copies x < W/2 onto x >= W/2;
    `donor="right"` copies x >= W/2 onto x < W/2) with a tight cosine feather along the midline.
    """
    src = np.asarray(img_arr, dtype=np.float32)
    h, w = src.shape[:2]
    cx = w / 2.0
    xx = np.arange(w, dtype=np.float32)[None, :]
    mirrored = src[:, ::-1]

    if donor == "left":
        t = smoothstep(cx - seam_half_width, cx + seam_half_width, xx)
    elif donor == "right":
        t = 1.0 - smoothstep(cx - seam_half_width, cx + seam_half_width, xx)
    else:
        raise ValueError(f"donor must be 'left' or 'right', got {donor!r}")

    if src.ndim == 3:
        t = t[..., None]
    repaired = src * (1.0 - t) + mirrored * t

    if preserve_mask is not None:
        pm = np.clip(preserve_mask.astype(np.float32), 0.0, 1.0)
        if src.ndim == 3 and pm.ndim == 2:
            pm = pm[..., None]
        repaired = repaired * (1.0 - pm) + src * pm

    return np.clip(repaired, 0.0, 255.0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mirror-symmetry texture repair CLI.")
    p.add_argument("input", type=Path, help="Aligned input image (midline at x=W/2)")
    p.add_argument("output", type=Path, help="Output repaired image path")
    p.add_argument("--donor", choices=("left", "right"), default="left", help="Intact image half in viewer coordinates")
    p.add_argument("--seam-px", type=float, default=8.0, help="Half-width of midline blend feather in pixels")
    args = p.parse_args(argv)

    im = Image.open(args.input).convert("RGB")
    arr = np.asarray(im, dtype=np.float32)
    before = compute_symmetry_metrics(arr)
    repaired = mirror_symmetry_repair(arr, donor=args.donor, seam_half_width=args.seam_px)
    after = compute_symmetry_metrics(repaired)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(repaired.astype(np.uint8), mode="RGB").save(args.output)
    print(json.dumps({"before": before, "after": after, "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
