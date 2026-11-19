import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from blender_ipc.ipc_client import BlenderIPCClient


class TestBlenderIPCClient(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ipc_dir = Path(self._tmp.name) / "ipc"
        self.client = BlenderIPCClient(ipc_dir=self.ipc_dir)

    def test_wait_ready(self):
        self.client.outbox.mkdir(parents=True, exist_ok=True)
        (self.client.outbox / "bridge_ready.json").write_text(
            json.dumps({"ready": True, "blender": "5.0.1"}), encoding="utf-8"
        )
        info = self.client.wait_ready(timeout=2.0)
        self.assertTrue(info["ready"])
        self.assertEqual(info["blender"], "5.0.1")

    def test_send_roundtrip_and_error(self):
        self.client.inbox.mkdir(parents=True, exist_ok=True)
        self.client.outbox.mkdir(parents=True, exist_ok=True)

        def mock_bridge():
            deadline = time.monotonic() + 5.0
            handled = 0
            while time.monotonic() < deadline and handled < 2:
                files = sorted(self.client.inbox.glob("*.json"))
                if files:
                    f = files[0]
                    payload = json.loads(f.read_text(encoding="utf-8"))
                    f.unlink()
                    ok = payload.get("action") != "fail_me"
                    resp = {"id": f.stem, "ok": ok, "output": "pong" if ok else "", "error": None if ok else "boom"}
                    (self.client.outbox / f"{f.stem}.json").write_text(json.dumps(resp), encoding="utf-8")
                    handled += 1
                time.sleep(0.02)

        t = threading.Thread(target=mock_bridge, daemon=True)
        t.start()

        res = self.client.ping(timeout=3.0)
        self.assertEqual(res["output"], "pong")

        with self.assertRaises(RuntimeError):
            self.client.send({"action": "fail_me"}, timeout=3.0)
        t.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
