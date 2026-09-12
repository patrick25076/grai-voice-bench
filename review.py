"""Build and serve a local listening study with durable, separate personal ratings.

Only explicit review files are served. Raw evidence and the label key are kept
outside the public directory. Labels become available after a saved rating.
This reduces label bias; recognizable voices and the operator's knowledge still
prevent a claim of fully blind independent evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

RUBRIC = ("naturalness", "clarity", "pace", "audibility", "handling", "personal_overall")
GATES = ("caller_fidelity", "spoken_truth", "spoken_consent")


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write(path, value):
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


def build(manifest, runs, output):
    plan = read(manifest)
    public = output / "public"
    (public / "audio").mkdir(parents=True, exist_ok=True)
    rows, labels = [], {}
    for index, trial in enumerate(plan["trials"], 1):
        sid = f"S{index:03d}"
        source = runs / trial["output_name"]
        wavs = sorted(source.glob("*.wav"))
        row = {
            "id": sid,
            "language": trial["language"],
            "audio": None,
            "audio_sha256": None,
            "status": "awaiting_recording",
        }
        if len(wavs) == 1:
            dest = public / "audio" / f"{sid}.wav"
            shutil.copyfile(wavs[0], dest)
            row.update(
                audio=f"/audio/{sid}.wav",
                status="ready",
                audio_sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
            )
        elif len(wavs) > 1:
            row["status"] = "needs_recording_selection"
        rows.append(row)
        labels[sid] = {
            k: trial[k]
            for k in ("trial_id", "pair_id", "provider", "caller_provider", "scenario", "language")
        }
        target = read(source / "agent-evidence.json", {}).get("lane_extra", {})
        caller = read(source / "caller-evidence.json", {}).get("lane_extra", {})
        labels[sid]["sandbox_evidence"] = target.get("benchmark")
        labels[sid]["caller_agenda"] = caller.get("benchmark", {}).get("caller_prompt")
    write(output / "labels.json", labels)
    write(
        public / "study.json",
        {"study_id": plan["study_id"], "samples": rows, "reviewer": plan["personal_reviewer"]},
    )
    shutil.copyfile(Path(__file__).with_name("review.html"), public / "index.html")
    return sum(row["audio"] is not None for row in rows)


def validate_vote(data, known):
    if not isinstance(data, dict) or data.get("sample_id") not in known:
        raise ValueError("Unknown sample")
    ratings = data.get("ratings", {})
    if set(ratings) != set(RUBRIC):
        raise ValueError("Every rubric item needs a rating or null for unscorable")
    if any(v is not None and (type(v) is not int or not 1 <= v <= 5) for v in ratings.values()):
        raise ValueError("Ratings must be integers 1..5 or null")
    gates = data.get("audio_review", {})
    if set(gates) != set(GATES) or any(
        v not in ("pass", "fail", "unreviewed") for v in gates.values()
    ):
        raise ValueError("Invalid audio review")
    notes = data.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 6000:
        raise ValueError("Notes too long")
    guess = data.get("recognized_provider", "unsure")
    if guess not in ("gemini", "gptlive", "unsure"):
        raise ValueError("Invalid recognition answer")
    boundaries = data.get("boundaries", [])
    if not isinstance(boundaries, list) or len(boundaries) > 100:
        raise ValueError("Invalid boundary annotations")
    for b in boundaries:
        if not isinstance(b, dict) or set(b) != {"kind", "seconds"}:
            raise ValueError("Invalid boundary annotation")
        if b["kind"] not in ("caller_end", "first_audio", "substantive", "completion"):
            raise ValueError("Invalid boundary kind")
        if (
            isinstance(b["seconds"], bool)
            or not isinstance(b["seconds"], (int, float))
            or not 0 <= b["seconds"] <= 300
        ):
            raise ValueError("Invalid audio time")
    return {
        "sample_id": data["sample_id"],
        "ratings": ratings,
        "audio_review": gates,
        "notes": notes,
        "recognized_provider": guess,
        "boundaries": boundaries,
    }


def serve(root, port):
    root = root.resolve()
    lock = threading.Lock()
    origin = f"http://127.0.0.1:{port}"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, value, code=200, mime="application/json"):
            body = (
                json.dumps(value, ensure_ascii=False).encode()
                if mime == "application/json"
                else value
            )
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self, mutation=False):
            return self.headers.get("Host") == f"127.0.0.1:{port}" and (
                not mutation or self.headers.get("Origin") == origin
            )

        def do_GET(self):
            if not self.allowed():
                return self.send({"error": "Use the displayed loopback address"}, 403)
            path = urlsplit(self.path).path
            if path == "/votes":
                with lock:
                    return self.send(read(root / "votes.json", {"samples": {}}))
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/study.json": ("study.json", "application/json"),
            }
            if re.fullmatch(r"/audio/S\d{3}\.wav", path):
                assets[path] = (path.lstrip("/"), "audio/wav")
            if path not in assets:
                return self.send({"error": "Not found"}, 404)
            name, mime = assets[path]
            file = root / "public" / name
            if not file.is_file():
                return self.send({"error": "Recording not available"}, 404)
            return self.send(
                read(file) if mime == "application/json" else file.read_bytes(), mime=mime
            )

        def do_POST(self):
            if not self.allowed(True):
                return self.send({"error": "Same-origin loopback requests only"}, 403)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 20000:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(size))
                with lock:
                    labels = read(root / "labels.json")
                    votes = read(root / "votes.json", {"samples": {}})
                    sid = data.get("sample_id")
                    if self.path == "/reveal":
                        if sid not in votes["samples"]:
                            raise ValueError("Save a rating before revealing labels")
                        entry = votes["samples"][sid]
                        entry.setdefault("revealed_at", datetime.now(UTC).isoformat())
                        write(root / "votes.json", votes)
                        return self.send(labels[sid])
                    if self.path != "/vote":
                        return self.send({"error": "Not found"}, 404)
                    vote = validate_vote(data, labels)
                    study = read(root / "public/study.json")
                    sample = next(s for s in study["samples"] if s["id"] == sid)
                    if not sample["audio"]:
                        raise ValueError("Cannot rate a sample without a recording")
                    entry = votes["samples"].setdefault(sid, {"history": []})
                    vote.update(
                        saved_at=datetime.now(UTC).isoformat(),
                        labels_previously_revealed="revealed_at" in entry,
                        audio_sha256=sample["audio_sha256"],
                        reviewer=study["reviewer"],
                    )
                    entry["history"].append(vote)
                    entry["latest"] = vote
                    write(root / "votes.json", votes)
                    return self.send({"saved": sid, "revision": len(entry["history"])})
            except (ValueError, TypeError, KeyError, StopIteration):
                return self.send({"error": "Invalid request or unavailable sample"}, 400)

    print(f"Listening review: {origin}/ — ratings saved to {root / 'votes.json'}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("build")
    for name in ("manifest", "runs", "output"):
        create.add_argument("--" + name, type=Path, required=True)
    server = commands.add_parser("serve")
    server.add_argument("root", type=Path)
    server.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    if args.command == "build":
        print(
            f"Prepared review: {build(args.manifest, args.runs, args.output)} recordings available"
        )
    else:
        serve(args.root, args.port)
