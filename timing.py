"""Offline recording and backend timing. No calls, regrading, or clock mixing.

Silero's recurrent ONNX input protocol is adapted from snakers4/silero-vad
(MIT, Copyright 2020-present Silero Team; see SILERO-LICENSE).
The segmentation/pairing rules below are analysis choices, not semantic labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import wave
from pathlib import Path

VERSION = "recording-timing-v1"
MODEL_SHA256 = "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
FRAME_MS = 32


def distribution(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "p50": None, "p95": None}
    return {
        "n": len(values),
        "p50": statistics.median(values),
        "p95": values[math.ceil(0.95 * len(values)) - 1],
    }


def speech_intervals(probabilities, duration_ms, silence_ms=400, threshold=0.5):
    """Hysteresis .5/.35, >=96 ms speech; no boundary padding.

    A 400 ms silence confirms an end, but the endpoint is the beginning of
    that silence: the detection hold is never added to the measured gap.
    """
    result, start, end = [], None, None
    for i, probability in enumerate(probabilities):
        at = i * FRAME_MS
        if probability >= threshold:
            end = None
            if start is None:
                start = at
        elif probability < threshold - 0.15 and start is not None:
            if end is None:
                end = at
            if at - end >= silence_ms:
                if end - start >= 96:
                    result.append([start, min(end, duration_ms)])
                start, end = None, None
    if start is not None:
        last = min(end if end is not None else duration_ms, duration_ms)
        if last - start >= 96:
            result.append([start, last])
    return result


def response_opportunities(caller, target):
    """Return every caller chunk, including overlaps and unpaired chunks.

    Overlap is not automatically a useful answer. It is reported separately
    and is NOT assigned zero latency or included in the positive-gap median.
    """
    rows = []
    for i, (start, end) in enumerate(caller):
        limit = caller[i + 1][0] if i + 1 < len(caller) else math.inf
        overlap = next(((a, b) for a, b in target if a < end < b), None)
        row = {"caller_start_ms": start, "caller_end_ms": end, "human_verified": False}
        if overlap:
            row.update(kind="overlap_at_caller_end", target_start_ms=overlap[0], gap_ms=None)
        else:
            response = next((a for a, _ in target if end <= a < limit), None)
            row.update(
                kind="nonoverlap_response" if response is not None else "no_paired_response",
                target_start_ms=response,
                gap_ms=response - end if response is not None else None,
            )
        rows.append(row)
    return rows


def backend_timing(audit):
    """Use receipt elapsed times from the SAME captured provider session.

    A backend response can end with tool requests and is not an audible answer.
    Continuations remain separate; no raw provider/session/account IDs exported.
    """
    output = []
    config_counts = {}
    for session_index, session in enumerate(audit.get("sessions", [])):
        pending, finished = {}, set()
        for event in session.get("events", []):
            data = event.get("data", {})
            if data.get("type") != "response.event":
                continue
            inner = data.get("event", {})
            response = inner.get("response", {})
            ident = response.get("id")
            kind = inner.get("type")
            elapsed = event.get("elapsed_ms")
            if kind == "response.created" and ident and isinstance(elapsed, (int, float)):
                pending.setdefault(ident, elapsed)
                config = (
                    response.get("model"),
                    (response.get("reasoning") or {}).get("effort"),
                    response.get("service_tier"),
                )
                config_counts[config] = config_counts.get(config, 0) + 1
            elif kind in {"response.completed", "response.failed", "response.incomplete"}:
                if ident in pending and ident not in finished:
                    if elapsed < pending[ident]:
                        raise ValueError("Non-monotonic backend receipt times")
                    finished.add(ident)
                    output.append({
                        "session_index": session_index,
                        "start_elapsed_ms": pending[ident],
                        "end_elapsed_ms": elapsed,
                        "duration_ms": elapsed - pending[ident],
                        "status": kind.removeprefix("response."),
                    })
        for ident, start in pending.items():
            if ident not in finished:
                output.append({"session_index": session_index, "start_elapsed_ms": start,
                               "end_elapsed_ms": None, "duration_ms": None, "status": "unclosed"})
    completed = [r["duration_ms"] for r in output if r["status"] == "completed"]
    return {
        "metric": "backend response.created to response.completed receipt elapsed time",
        "scope": "GPT backend diagnostic only; not caller silence, speech latency, or whole delegation duration",
        "completed_ms": distribution(completed),
        "responses": output,
        "configurations": [{"model": k[0], "reasoning_effort": k[1], "service_tier": k[2], "n": v}
                           for k, v in sorted(config_counts.items(), key=lambda x: str(x[0]))],
    }


class SpeechDetector:
    def __init__(self, model_path):
        import onnxruntime as ort

        if hashlib.sha256(Path(model_path).read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError("This analysis version requires the documented Silero model SHA-256")
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_path), sess_options=opts,
                                           providers=["CPUExecutionProvider"])

    def probabilities(self, samples, rate):
        import numpy as np

        if rate not in (8000, 16000):
            raise ValueError("Use original 8 or 16 kHz PCM; resampling is not implicit")
        width, context_width = rate * 32 // 1000, rate * 4 // 1000
        state = np.zeros((2, 1, 128), dtype=np.float32)
        context = np.zeros((1, context_width), dtype=np.float32)
        result = []
        for at in range(0, len(samples), width):
            frame = np.zeros((1, width), dtype=np.float32)
            values = samples[at:at + width]
            frame[0, :len(values)] = values / 32768.0
            full = np.concatenate((context, frame), axis=1)
            probability, state = self.session.run(None, {
                "input": full, "state": state, "sr": np.array(rate, dtype=np.int64),
            })
            context = full[:, -context_width:]
            result.append(float(probability[0][0]))
        return result


def recording_timing(path, detector, caller_channel=0, cache=None):
    import numpy as np

    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 2 or caller_channel not in (0, 1):
            raise ValueError("Two-channel PCM16 and an explicit caller channel are required")
        rate = wav.getframerate()
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, 2)
    duration_ms = len(pcm) * 1000 / rate
    cache_path = Path(cache) / f"{digest}-{MODEL_SHA256[:12]}.json" if cache else None
    if cache_path and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached["audio_sha256"] != digest or cached["model_sha256"] != MODEL_SHA256:
            raise ValueError("VAD cache fingerprint mismatch")
        probabilities = cached["probabilities"]
    else:
        probabilities = [detector.probabilities(pcm[:, channel], rate) for channel in range(2)]
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"audio_sha256": digest, "model_sha256": MODEL_SHA256,
                                             "probabilities": probabilities}), encoding="utf-8")
    channels = [speech_intervals(p, duration_ms) for p in probabilities]
    opportunities = response_opportunities(channels[caller_channel], channels[1 - caller_channel])
    gaps = [r["gap_ms"] for r in opportunities if r["gap_ms"] is not None]
    last_speech = max((b for channel in channels for _, b in channel), default=None)
    first_speech = min((a for channel in channels for a, _ in channel), default=None)
    sensitivity = []
    for silence in (250, 700):
        candidate = [speech_intervals(p, duration_ms, silence_ms=silence) for p in probabilities]
        rows = response_opportunities(candidate[caller_channel], candidate[1 - caller_channel])
        sensitivity.append({"silence_ms": silence, "nonoverlap_gap_ms": distribution(
            [r["gap_ms"] for r in rows if r["gap_ms"] is not None])})
    # Peaks are display-only, never fed back into measurements. Both channels
    # share the same full-scale reference; no gain normalization or speed edit.
    width = max(1, rate // 10)
    peaks = [[round(float(np.max(np.abs(pcm[i:i + width, c].astype(np.int32)))) / 32768, 4)
              for i in range(0, len(pcm), width)] for c in range(2)]
    return {
        "analysis_version": VERSION,
        "audio_sha256": digest,
        "model_sha256": MODEL_SHA256,
        "sample_rate": rate,
        "caller_channel": caller_channel,
        "duration_ms": duration_ms,
        "speech_intervals_ms": channels,
        "opportunities": opportunities,
        "nonoverlap_gap_ms": distribution(gaps),
        "overlap_at_caller_end_count": sum(r["kind"] == "overlap_at_caller_end" for r in opportunities),
        "no_paired_response_count": sum(r["kind"] == "no_paired_response" for r in opportunities),
        "last_detected_speech_ms": last_speech,
        "first_detected_speech_ms": first_speech,
        "trailing_no_detected_speech_ms": duration_ms - last_speech if last_speech is not None else None,
        "detected_conversation_span_ms": last_speech - first_speech if last_speech is not None else None,
        "sensitivity": sensitivity,
        "display_peaks_100ms": peaks,
        "human_verified_boundaries": 0,
        "method": "Silero ONNX, 32ms frames, .5/.35 hysteresis, 96ms minimum speech, 400ms silence, no padding",
        "limitation": "Automated speech chunks, not semantic turns; overlap and unpaired chunks shown separately. First detected speech may be acknowledgment, not answer. Includes phone path. No pure model or human-validated latency claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--vad-model", type=Path, required=True)
    parser.add_argument("--caller-channel", type=int, choices=(0, 1), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = recording_timing(args.recording, SpeechDetector(args.vad_model), args.caller_channel)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
