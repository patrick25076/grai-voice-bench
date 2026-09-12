"""Observe pinned SDK config/usage before normalization, without changing audio.

These private SDK hooks are verified against livekit plugins 1.8.1. Refuse a
different version instead of silently losing evidence. Raw provider usage is
retained for reconciliation; its events must NOT simply be added together.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path


def runtime_fingerprint():
    import voicelab.simulations

    lane = Path(__file__).resolve().parent
    package = Path(voicelab.simulations.__file__).resolve().parents[1]
    files = {
        name: lane / name for name in ("worker.py", "benchmark_support.py", "provider_audit.py")
    }
    for folder, names in {
        "bench": (
            "__init__.py",
            "world.py",
            "packs.py",
            "generate.py",
            "agent.py",
            "tools.py",
            "suite.py",
        ),
        "simulations": ("__init__.py", "sandbox.py", "cases.py"),
        "tools": ("__init__.py",),
    }.items():
        files.update({f"{folder}/{name}": package / folder / name for name in names})
    return {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items())
    }


def plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    return json.loads(json.dumps(value))


def attach_audit(model, provider, evidence):
    package = "livekit-plugins-openai" if provider == "gptlive" else "livekit-plugins-google"
    version = importlib.metadata.version(package)
    if version != "1.8.1":
        raise RuntimeError(f"Provider audit needs verified {package}==1.8.1; found {version}")
    audit = {
        "sdk_package": package,
        "sdk_version": version,
        "sessions": [],
        "usage_interpretation": "raw events; cumulative and response scopes require reconciliation",
    }
    evidence["provider_audit"] = audit
    original_session = model.session

    def session(*args, **kwargs):
        result = original_session(*args, **kwargs)
        start = time.monotonic()
        record = {"opened_at_unix": time.time(), "events": []}
        audit["sessions"].append(record)

        def save(kind, data):
            record["events"].append(
                {"kind": kind, "elapsed_ms": (time.monotonic() - start) * 1000, "data": plain(data)}
            )

        if provider == "gptlive":
            original_config = result._session_start_event
            original_event = result._handle_event

            def config():
                value = original_config()
                save("requested_config", value)
                return value

            def event(value):
                kind = value.get("type", "")
                # PCM deltas are in the carrier WAV; do not duplicate base64 here.
                if kind != "session.output_audio.delta":
                    save("provider_event", value)
                return original_event(value)

            result._session_start_event = config
            result._handle_event = event
        else:
            original_config = result._build_connect_config
            original_usage = result._handle_usage_metadata

            def config():
                value = original_config()
                save("requested_config", value)
                return value

            def usage(value):
                save("usage_metadata", value)
                return original_usage(value)

            result._build_connect_config = config
            result._handle_usage_metadata = usage
        return result

    model.session = session
    return audit
