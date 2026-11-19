# blender-swarm-kit

Reusable, standalone 3D-reconstruction, interactive Blender 5.0+ GUI automation, mesh QA, WebGL STL inspection, and Collapsible Live Gantt Swarm Tracker toolkit — extracted from [Operation Dumb Bunny](https://github.com/bsommers/dumb-bunny) for easy assimilation into any repository.

## Modules

| Path | Purpose | Dependencies |
|---|---|---|
| `blender_ipc/live_bridge.py` | Interactive (non-headless) Blender 5.0+ GUI IPC server (`bpy.app.timers` polling atomic JSON inbox/outbox) with 3-point studio lighting, live viewport snapshot rendering, and optional turntable orbit (`off` by default) | Blender 5.0+ Python (`bpy`) |
| `blender_ipc/ipc_client.py` | Sandbox-friendly file-based IPC client (`--wait`, `--ping`, `--status`, `--exec-code`, `--snapshot`, `--orbit`, `<script.py>`) — lets sandboxed agents drive a live host Blender window | Python 3 stdlib only |
| `gantt_tracker/server.py` | Zero-dependency live web tracker HTTP server (`--root`, `--state`, `--port`, `/api/state`, `/healthz`, confined static file prefixes) | Python 3 stdlib only |
| `gantt_tracker/tracker_util.py` | Atomic, `O_EXCL`-locked JSON state manager & CLI (`init`, `agent`, `stage`, `event`) safe for concurrent parallel agents | Python 3 stdlib only |
| `gantt_tracker/index.html` | Collapsible Live Gantt Chart Mission Control HUD (parallel agent swimlanes, pipeline phase rows, adaptive elapsed-time ruler, glowing live NOW cursor, non-flickering tooltips, zero-flicker live viewport feed, before/after comparison slider) | Vanilla HTML/CSS/JS |
| `mesh_qa/stl_verify.py` | Pure-Python binary STL watertightness, 2-manifold edge check, connected shell count, Euler characteristic ($\chi = V - E + F$), signed volume ($\text{cm}^3$), bilateral X-symmetry RMS (`cKDTree`), plus OBJ/MTL/texture & `.blend` magic verifier | `numpy`, `scipy` |
| `mesh_qa/symmetry_repair.py` | Reusable bilateral mirror symmetry repair, crisp directional/harmonic crack inpainting, isotropic micro-grain, symmetry metrics, and strictly X-symmetric float32 heightmap builder (`max_abs_sym_err == 0.0`) | `numpy`, `scipy`, `Pillow` |
| `mesh_qa/multiview_calibrate.py` | Shadow-invariant CIE-Lab foreground segmentation & height-aligned RGBA orthographic reference plate builder | `numpy`, `scipy`, `Pillow` |
| `stl_viewer/` | Zero-dependency WebGL Phong / TRON Grid / Wireframe binary STL viewer (`stl-viewer.js`) with Canvas 2D fallback & drag-and-drop `demo.html` | Vanilla JS |
| `rules/web-tracker-gantt.md` | Drop-in agent rule requiring a collapsible live Gantt chart panel at the top of every web tracker UI | Markdown |

## Quick Start

### 1. Drive Live Interactive Blender 5.0+ GUI from Any Agent (Even Sandboxed)
```bash
# Terminal 1 (on host desktop, outside sandbox):
/Applications/Blender.app/Contents/MacOS/Blender \
  --python ~/src/tools/blender-swarm-kit/blender_ipc/live_bridge.py -- \
  --root /path/to/your-project

# Terminal 2 (inside agent sandbox or another shell):
python3 ~/src/tools/blender-swarm-kit/blender_ipc/ipc_client.py --ipc-dir /path/to/your-project/work/blender_ipc --wait
python3 ~/src/tools/blender-swarm-kit/blender_ipc/ipc_client.py --ipc-dir /path/to/your-project/work/blender_ipc --ping
python3 ~/src/tools/blender-swarm-kit/blender_ipc/ipc_client.py --ipc-dir /path/to/your-project/work/blender_ipc my_sculpt_stage.py
python3 ~/src/tools/blender-swarm-kit/blender_ipc/ipc_client.py --ipc-dir /path/to/your-project/work/blender_ipc --snapshot hero.png --label "Hero 3/4"
```

### 2. Launch the Collapsible Live Gantt Mission Control Tracker
```bash
export PYTHONPATH=~/src/tools/blender-swarm-kit
python3 -m gantt_tracker.tracker_util --state ./work/tracker_state.json init "My Swarm Project" --model "Claude / Gemini"
python3 -m gantt_tracker.server --root . --port 8765
# Open http://127.0.0.1:8765
```

### 3. Verify 3D-Printable STL / OBJ / .blend Deliverables
```bash
python3 ~/src/tools/blender-swarm-kit/mesh_qa/stl_verify.py \
  output/model.stl output/mask.stl output/model.obj models/scene.blend \
  --check-symmetry --expected-height-mm 180
```

### 4. Run Tests
```bash
python3 -m unittest discover -s tests -v
```

## Assimilation Guide (Using From Other Repos)

- **Cataloged in:** `~/src/tools/build-tooling` (`build-tooling where blender-swarm-kit`) and `~/src/swe/swe-skills-2` (`tool-registry.py show blender-swarm-kit`).
- **Copy a single module** (each package is self-contained) or add `~/src/tools/blender-swarm-kit` to `PYTHONPATH`.
- **Copy `rules/web-tracker-gantt.md`** into `.agents/rules/` in any repo to enforce the collapsible live Gantt chart standard across agent sessions.

## License

MIT — see [LICENSE](LICENSE).
