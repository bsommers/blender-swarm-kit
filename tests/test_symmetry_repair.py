import unittest

import numpy as np

from mesh_qa.symmetry_repair import (
    compute_symmetry_metrics,
    enforce_strict_x_symmetry,
    mirror_symmetry_repair,
)


class TestSymmetryRepair(unittest.TestCase):
    def test_mirror_symmetry_repair_heals_damaged_half(self):
        h, w = 64, 64
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        # Smooth symmetric pattern
        base = 120.0 + 40.0 * np.cos((xx - w / 2.0) / 12.0) * np.cos((yy - h / 2.0) / 12.0)
        img = np.stack([base, base * 0.85, base * 0.72], axis=-1)
        # Inject heavy crack damage on the viewer-right (+X) half
        damaged = img.copy()
        damaged[16:50, 40:58] = 15.0

        before = compute_symmetry_metrics(damaged)
        repaired = mirror_symmetry_repair(damaged, donor="left", seam_half_width=4.0)
        after = compute_symmetry_metrics(repaired)

        self.assertLess(before["overall_symmetry_pct"], 88.0)
        self.assertGreater(after["overall_symmetry_pct"], 99.0)

    def test_strict_x_symmetry_heightmap(self):
        rng = np.random.default_rng(7)
        h = rng.uniform(0.0, 1.0, size=(32, 32)).astype(np.float32)
        sym = enforce_strict_x_symmetry(h)
        max_err = float(np.max(np.abs(sym - sym[:, ::-1])))
        self.assertEqual(max_err, 0.0)


if __name__ == "__main__":
    unittest.main()
