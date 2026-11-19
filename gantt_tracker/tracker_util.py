#!/usr/bin/env python3
"""
Atomic, lock-protected JSON state manager for the Collapsible Live Gantt Web Tracker.

Safe for concurrent multi-agent updates via O_EXCL advisory lockfile + atomic temp-file
rename (`os.replace`). Zero external dependencies (Python 3 stdlib only).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

LOCK_STALE_SEC = 30.0


def default_state_path(root: str | Path | None = None) -> Path:
    if os.environ.get("GANTT_TRACKER_STATE"):
        return Path(os.environ["GANTT_TRACKER_STATE"]).expanduser().resolve()
    base = Path(root or os.environ.get("GANTT_TRACKER_ROOT") or os.getcwd()).expanduser().resolve()
    return base / "work" / "tracker_state.json"


def now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextlib.contextmanager
def state_lock(state_path: Path, timeout: float = 15.0):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lp = state_path.parent / f".{state_path.name}.lock"
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lp.stat().st_mtime > LOCK_STALE_SEC:
                    lp.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"Could not acquire lock {lp}")
            time.sleep(0.01)
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            lp.unlink()


def load_state(state_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(state_path).expanduser().resolve() if state_path else default_state_path()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict[str, Any], state_path: str | Path | None = None) -> None:
    path = Path(state_path).expanduser().resolve() if state_path else default_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tracker.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def init_state(
    project: str,
    subtitle: str = "Parallel Agent Swarm Telemetry",
    model_label: str = "AI Swarm",
    stages: list[dict[str, Any]] | None = None,
    agents: list[dict[str, Any]] | None = None,
    state_path: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    path = Path(state_path).expanduser().resolve() if state_path else default_state_path()
    with state_lock(path):
        if path.exists() and not force:
            raise FileExistsError(f"State file already exists at {path} (pass force=True to overwrite)")
        state: dict[str, Any] = {
            "project": project,
            "subtitle": subtitle,
            "model_banner": model_label,
            "started_at": now_iso(),
            "overall_progress": 0,
            "current_stage": "Initialized",
            "pipeline_stages": stages
            or [
                {"id": "plan", "label": "Plan & Spec", "status": "PENDING"},
                {"id": "build", "label": "Parallel Build", "status": "PENDING"},
                {"id": "verify", "label": "QA & Verify", "status": "PENDING"},
            ],
            "agents": agents or [],
            "blender_live": {
                "connected": False,
                "status": "STANDBY",
                "stage": "Waiting for live viewport capture...",
                "latest_render": None,
                "renders": [],
            },
            "compare": None,
            "references": [],
            "outputs": [],
            "events": [{"time": now_hms(), "source": "SYSTEM", "msg": f"Initialized {project}"}],
        }
        save_state(state, path)
        return state


def update_agent(
    agent_id: str,
    status: str | None = None,
    progress: int | float | None = None,
    task: str | None = None,
    log: str | None = None,
    metrics: dict[str, Any] | None = None,
    name: str | None = None,
    role: str | None = None,
    model: str | None = None,
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(state_path).expanduser().resolve() if state_path else default_state_path()
    with state_lock(path):
        state = load_state(path)
        target = None
        for a in state.setdefault("agents", []):
            if a["id"] == agent_id:
                target = a
                break
        if target is None:
            target = {
                "id": agent_id,
                "name": name or agent_id,
                "role": role or "Worker",
                "model": model or state.get("model_banner", "AI"),
                "status": "QUEUED",
                "progress": 0,
                "current_task": "",
                "logs": [],
                "metrics": {},
            }
            state["agents"].append(target)

        if name is not None:
            target["name"] = name
        if role is not None:
            target["role"] = role
        if model is not None:
            target["model"] = model
        if status is not None:
            target["status"] = status
        if progress is not None:
            target["progress"] = progress
        if task is not None:
            target["current_task"] = task
        if log:
            target.setdefault("logs", []).append(f"[{now_hms()}] {log}")
            target["logs"] = target["logs"][-20:]
            state.setdefault("events", []).append({"time": now_hms(), "source": agent_id.upper(), "msg": log})
            state["events"] = state["events"][-50:]
        if metrics:
            target.setdefault("metrics", {}).update(metrics)
        save_state(state, path)
        return state


def update_stage(
    stage_id: str,
    status: str,
    overall_progress: int | float | None = None,
    current_stage: str | None = None,
    event_msg: str | None = None,
    label: str | None = None,
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(state_path).expanduser().resolve() if state_path else default_state_path()
    with state_lock(path):
        state = load_state(path)
        found = False
        for s in state.setdefault("pipeline_stages", []):
            if s["id"] == stage_id:
                s["status"] = status
                if label is not None:
                    s["label"] = label
                found = True
                break
        if not found:
            state["pipeline_stages"].append({"id": stage_id, "label": label or stage_id, "status": status})
        if overall_progress is not None:
            state["overall_progress"] = overall_progress
        if current_stage is not None:
            state["current_stage"] = current_stage
        if event_msg:
            state.setdefault("events", []).append({"time": now_hms(), "source": "PIPELINE", "msg": event_msg})
            state["events"] = state["events"][-50:]
        save_state(state, path)
        return state


def update_blender(
    connected: bool | None = None,
    status: str | None = None,
    stage: str | None = None,
    latest_render: str | None = None,
    render_label: str | None = None,
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(state_path).expanduser().resolve() if state_path else default_state_path()
    with state_lock(path):
        state = load_state(path)
        bl = state.setdefault(
            "blender_live",
            {"connected": False, "status": "STANDBY", "stage": "", "latest_render": None, "renders": []},
        )
        if connected is not None:
            bl["connected"] = connected
        if status is not None:
            bl["status"] = status
        if stage is not None:
            bl["stage"] = stage
        if latest_render is not None:
            bl["latest_render"] = latest_render
            entry = {"url": latest_render, "label": render_label or stage or "Live Capture", "time": now_hms()}
            bl["renders"] = [r for r in bl.get("renders", []) if r["url"] != latest_render] + [entry]
            bl["renders"] = bl["renders"][-16:]
        save_state(state, path)
        return state


def append_event(source: str, msg: str, state_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(state_path).expanduser().resolve() if state_path else default_state_path()
    with state_lock(path):
        state = load_state(path)
        state.setdefault("events", []).append({"time": now_hms(), "source": source, "msg": msg})
        state["events"] = state["events"][-50:]
        save_state(state, path)
        return state


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Atomic state CLI for the Collapsible Live Gantt Tracker.")
    p.add_argument("--state", help="Path to tracker_state.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="Initialize a fresh tracker_state.json")
    pi.add_argument("project", help="Project display name")
    pi.add_argument("--subtitle", default="Parallel Agent Swarm Telemetry")
    pi.add_argument("--model", default="AI Swarm")
    pi.add_argument("--force", action="store_true")

    pa = sub.add_parser("agent", help="Update or register an agent swimlane")
    pa.add_argument("id")
    pa.add_argument("--status", choices=("QUEUED", "RUNNING", "DONE", "ERROR"))
    pa.add_argument("--progress", type=float)
    pa.add_argument("--task")
    pa.add_argument("--log")
    pa.add_argument("--name")
    pa.add_argument("--role")
    pa.add_argument("--model")

    ps = sub.add_parser("stage", help="Update a pipeline stage")
    ps.add_argument("id")
    ps.add_argument("status", choices=("PENDING", "RUNNING", "ACTIVE", "DONE", "ERROR"))
    ps.add_argument("--overall", type=float)
    ps.add_argument("--label")
    ps.add_argument("--msg")

    pe = sub.add_parser("event", help="Append an event log entry")
    pe.add_argument("source")
    pe.add_argument("message", nargs="+")

    args = p.parse_args(argv)
    if args.cmd == "init":
        init_state(args.project, subtitle=args.subtitle, model_label=args.model, state_path=args.state, force=args.force)
    elif args.cmd == "agent":
        update_agent(
            args.id,
            status=args.status,
            progress=args.progress,
            task=args.task,
            log=args.log,
            name=args.name,
            role=args.role,
            model=args.model,
            state_path=args.state,
        )
    elif args.cmd == "stage":
        update_stage(
            args.id,
            args.status,
            overall_progress=args.overall,
            label=args.label,
            event_msg=args.msg,
            state_path=args.state,
        )
    elif args.cmd == "event":
        append_event(args.source, " ".join(args.message), state_path=args.state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
