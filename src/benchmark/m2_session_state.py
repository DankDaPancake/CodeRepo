"""Durable, conservative record of M2 benchmark session interruptions."""

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path


def _now():
    return datetime.now(UTC).isoformat()


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf8")
    os.replace(temp, path)


def begin_session(path: Path, *, previous_session_stopped: bool = False) -> str:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf8")) if path.exists() else {"sessions": []}
    sessions = data["sessions"]
    if sessions and sessions[-1]["status"] == "active":
        if not previous_session_stopped:
            raise RuntimeError("Previous session may still be running; verify it has stopped")
        sessions[-1]["status"] = "interrupted"
        sessions[-1]["interruption_detected_at"] = _now()
    sid = uuid.uuid4().hex
    sessions.append({"id": sid, "status": "active", "started_at": _now()})
    data["measurement_complete"] = False
    _save(path, data)
    return sid


def finish_session(path: Path, session_id: str, returncode: int) -> None:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf8"))
    if not data["sessions"] or data["sessions"][-1]["id"] != session_id:
        raise ValueError("Session identity changed")
    session = data["sessions"][-1]
    if session["status"] != "active":
        raise ValueError("Session is not active")
    session.update(status="complete" if returncode == 0 else "interrupted", ended_at=_now())
    session["returncode"] = returncode
    data["measurement_complete"] = all(s["status"] == "complete" for s in data["sessions"])
    _save(path, data)


def annotate_report(state_file: Path, report_dir: Path) -> None:
    """Mark measurements incomplete when a session was lost, without inventing a duration."""
    import csv

    data = json.loads(Path(state_file).read_text(encoding="utf8"))
    report = Path(report_dir)
    report.mkdir(parents=True, exist_ok=True)
    audit = {
        "measurement_complete": data["measurement_complete"],
        "interrupted_sessions": sum(s["status"] == "interrupted" for s in data["sessions"]),
        "note": (
            "Interrupted session durations and peaks may be missing; "
            "observed values are lower bounds."
        ),
    }
    _save(report / "measurement_audit.json", audit)
    summary = report / "m2_benchmark_summary.csv"
    if data["measurement_complete"] or not summary.is_file():
        return
    with summary.open(encoding="utf8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    for row in rows:
        if row["metric"] in {"wall_time_e2e", "time_per_paper", "ram_max", "disk_max"}:
            if "lower bound" not in row["tool"]:
                row["tool"] += "; lower bound (interrupted session)"
        elif row["metric"] == "ram_mean" and "incomplete" not in row["tool"]:
            row["tool"] += "; incomplete sessions, not representative"
    with summary.open("w", encoding="utf8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
