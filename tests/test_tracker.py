import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from gantt_tracker.server import build_server
from gantt_tracker.tracker_util import init_state, load_state, update_agent, update_blender, update_stage


class TestGanttTracker(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.state_path = self.root / "work" / "tracker_state.json"

    def test_state_lifecycle_and_http_server(self):
        init_state("Test Mission", state_path=self.state_path)
        update_agent("worker-1", status="RUNNING", progress=50, task="Sculpting", log="Halfway", state_path=self.state_path)
        update_stage("build", "RUNNING", overall_progress=50, current_stage="Building", state_path=self.state_path)
        update_blender(connected=True, status="LIVE", latest_render="/tracker/live_renders/snap.png", state_path=self.state_path)

        st = load_state(self.state_path)
        self.assertEqual(st["project"], "Test Mission")
        self.assertEqual(st["agents"][0]["progress"], 50)
        self.assertTrue(st["blender_live"]["connected"])

        # Write an allowed file and a forbidden file outside allowed prefixes
        (self.root / "work" / "note.txt").write_text("hello", encoding="utf-8")
        (self.root / "secret.txt").write_text("nope", encoding="utf-8")

        srv = build_server(root=self.root, state_path=self.state_path, host="127.0.0.1", port=0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))

        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base + "/healthz") as r:
            self.assertEqual(r.read().decode(), "ok")
        with urllib.request.urlopen(base + "/") as r:
            html = r.read().decode()
            self.assertIn("Live Mission Gantt Timeline", html)
        with urllib.request.urlopen(base + "/api/state") as r:
            data = json.loads(r.read().decode())
            self.assertEqual(data["project"], "Test Mission")
        with urllib.request.urlopen(base + "/work/note.txt") as r:
            self.assertEqual(r.read().decode(), "hello")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(base + "/work/../secret.txt")
        self.assertIn(ctx.exception.code, (403, 404))

    def test_concurrent_cli_writers(self):
        init_state("Concurrency Test", state_path=self.state_path)
        kit_root = Path(__file__).resolve().parent.parent
        procs = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "gantt_tracker.tracker_util",
                    "--state",
                    str(self.state_path),
                    "agent",
                    f"a{i}",
                    "--status",
                    "DONE",
                    "--progress",
                    "100",
                    "--log",
                    f"done-{i}",
                ],
                cwd=str(kit_root),
            )
            for i in range(10)
        ]
        self.assertTrue(all(p.wait() == 0 for p in procs))
        st = load_state(self.state_path)
        self.assertEqual(len(st["agents"]), 10)


if __name__ == "__main__":
    unittest.main()
