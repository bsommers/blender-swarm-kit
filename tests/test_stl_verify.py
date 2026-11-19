import struct
import tempfile
import unittest
from pathlib import Path

from mesh_qa.stl_verify import audit_blend, audit_obj_mtl, audit_stl


def write_binary_stl(path: Path, tris: list[tuple[tuple[float, float, float], ...]]) -> None:
    buf = bytearray(80)
    buf[:12] = b"syntheticstl"
    buf.extend(struct.pack("<I", len(tris)))
    for v0, v1, v2 in tris:
        buf.extend(struct.pack("<3f", 0.0, 0.0, 0.0))
        buf.extend(struct.pack("<3f", *v0))
        buf.extend(struct.pack("<3f", *v1))
        buf.extend(struct.pack("<3f", *v2))
        buf.extend(struct.pack("<H", 0))
    path.write_bytes(bytes(buf))


def unit_cube_tris(size: float = 20.0) -> list[tuple[tuple[float, float, float], ...]]:
    h = size / 2.0
    v = [
        (-h, -h, 0.0), (h, -h, 0.0), (h, h, 0.0), (-h, h, 0.0),
        (-h, -h, size), (h, -h, size), (h, h, size), (-h, h, size),
    ]
    faces = [
        (0, 2, 1), (0, 3, 2),  # bottom (-Z)
        (4, 5, 6), (4, 6, 7),  # top (+Z)
        (0, 1, 5), (0, 5, 4),  # front (-Y)
        (2, 3, 7), (2, 7, 6),  # back (+Y)
        (0, 4, 7), (0, 7, 3),  # left (-X)
        (1, 2, 6), (1, 6, 5),  # right (+X)
    ]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


class TestSTLVerify(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)

    def test_watertight_symmetric_cube(self):
        p = self.d / "cube.stl"
        write_binary_stl(p, unit_cube_tris(20.0))
        rep = audit_stl(p, expected_height_mm=20.0, height_tol_mm=1.0, check_symmetry=True)
        self.assertTrue(rep["pass"], rep["issues"])
        self.assertTrue(rep["topology"]["watertight_manifold"])
        self.assertEqual(rep["topology"]["connected_components"], 1)
        self.assertEqual(rep["topology"]["euler_characteristic"], 2)
        self.assertAlmostEqual(rep["signed_volume_cm3"], 8.0, places=2)
        self.assertAlmostEqual(rep["bilateral_symmetry_x"]["rms_about_x0_mm"], 0.0, places=4)

    def test_open_mesh_fails_watertight(self):
        p = self.d / "open.stl"
        write_binary_stl(p, unit_cube_tris(20.0)[:-1])
        rep = audit_stl(p)
        self.assertFalse(rep["pass"])
        self.assertFalse(rep["topology"]["watertight_manifold"])
        self.assertGreater(rep["topology"]["boundary_edges_1"], 0)

    def test_obj_mtl_and_blend_headers(self):
        obj = self.d / "m.obj"
        mtl = self.d / "m.mtl"
        tex = self.d / "t.png"
        tex.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        mtl.write_text("newmtl MatA\nmap_Kd t.png\n", encoding="utf-8")
        obj.write_text("mtllib m.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nusemtl MatA\nf 1/1 2/1 3/1\n", encoding="utf-8")
        rep = audit_obj_mtl(obj, require_textures=True)
        self.assertTrue(rep["pass"], rep["issues"])

        bl = self.d / "scene.blend"
        bl.write_bytes(b"BLENDER-v501" + b"\x00" * 64)
        brep = audit_blend(bl)
        self.assertTrue(brep["pass"])
        self.assertEqual(brep["format"], "uncompressed_blend")


if __name__ == "__main__":
    unittest.main()
