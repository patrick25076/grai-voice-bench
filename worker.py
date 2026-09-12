"""Shared Gemini Live / GPT-Live phone worker for GRAI Voice Bench.

A different topology from the bridge lanes: no websocket of ours is in the audio
path at all. Twilio Elastic SIP Trunking hands the call to LiveKit Cloud over
SIP/TCP, LiveKit's SIP service transcodes PCMU 8 kHz into an Opus track in a
room, and this worker joins that room. So there is no CarrierSerializer here
(nothing parses carrier JSON) and no voicelab.audio here (LiveKit has already
resampled before we ever see a frame). The one thing this lane does share is the
Scorecard, so the bake-off compares like with like.

The original bare mode has no clinic config, no tenant YAML, no tools, no database, no
noise cancellation, and — the one that matters — no LiveKit turn-detector model
inserted into the turn loop (see BARE-NESS notes below).

VOICELAB_BENCHMARK=1 adds shared fictional business tools and scenario metadata
for both providers. It never imports production tenant configurations.

Run:
    uv run python worker.py console   # local mic/speakers, no LiveKit, no phone
    uv run python worker.py dev       # register with LiveKit Cloud, hot reload
    uv run python worker.py start     # same as dev, production logging
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import hmac
import json
import logging
import os
import socket
import time
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.genai import types as genai_types
from livekit import agents, rtc
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions
from livekit.plugins import google
from livekit.plugins.openai.realtime import GPTLiveModel

try:
    # Mandatory for this lane. Without it we cannot pin turn_detection, and an
    # unpinned session is free to insert LiveKit's own turn-detector model —
    # exactly the extra processing this bake-off exists to eliminate.
    from livekit.agents import TurnHandlingOptions
except ImportError as exc:  # pragma: no cover - install-time failure, not runtime
    raise RuntimeError(
        "livekit-agents is too old: TurnHandlingOptions is missing. "
        "This lane needs >=1.7 (`uv sync` in apps/voicelab/lanes-external/livekit)."
    ) from exc

LANE = "livekit"
logger = logging.getLogger("voicelab.livekit")

load_dotenv(Path(__file__).parent / ".env")


# --------------------------------------------------------------------------- #
# env
# --------------------------------------------------------------------------- #


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw else default


def _env_flag(name: str, default: str = "1") -> bool:
    return _env(name, default).lower() in {"1", "true", "yes", "on"}


#: Which arm this worker is. "gemini" (default, the original lane) or "gptlive".
#: One worker binary, two arms, so the topology is provably identical.
PROVIDER = (_env("VOICELAB_PROVIDER", "gemini") or "gemini").strip().lower()
MODEL = _env("VOICELAB_MODEL", "gemini-3.1-flash-live-preview")
GPTLIVE_MODEL = _env("VOICELAB_GPTLIVE_MODEL", "gpt-live-1")
GPTLIVE_VOICE = _env("VOICELAB_GPTLIVE_VOICE", "marin")
#: The delegated reasoning model. LiveKit's own example names gpt-5.6-luna.
GPTLIVE_BACKEND = _env("VOICELAB_GPTLIVE_BACKEND", "gpt-5.6-terra")
#: Sections that are conversational behaviour and belong in the VOICE prompt.
LIVE_SECTIONS = ("LANGUAGE", "HOW YOU SOUND", "HOW YOU SPEAK", "PRIVACY")
VOICE = _env("VOICELAB_VOICE", "Puck")
AGENT_NAME = _env("VOICELAB_AGENT_NAME", "voicelab-livekit")
# Which carrier is feeding LiveKit's SIP service. Only a scorecard label here —
# this lane never speaks the carrier's protocol itself.
CARRIER = _env("VOICELAB_CARRIER", "twilio")
SCORECARD_DIR = Path(_env("VOICELAB_SCORECARD_DIR", "./scorecards"))
WATCHDOG_S = _env_float("VOICELAB_WATCHDOG_S", 8.0)
PARTICIPANT_WAIT_S = _env_float("VOICELAB_PARTICIPANT_WAIT_S", 10.0)
# 16 kHz is what the Gemini plugin wants. LiveKit's RoomIO otherwise hands the
# session 24 kHz frames and the plugin resamples 24 -> 16 itself; asking RoomIO
# for 16 kHz directly deletes one resample stage from the inbound path. Set to 0
# to leave RoomIO on its 24 kHz default and measure the difference.
ROOM_INPUT_RATE = int(_env("VOICELAB_ROOM_INPUT_RATE", "16000") or 0)
ROOMIO_DEFAULT_RATE = 24000
# OFF by default, and that is a bare-ness decision, not a preference. RoomIO's
# AudioInputOptions.auto_gain_control defaults to True, and when it is on
# _ParticipantAudioInputStream builds an rtc.AudioProcessingModule and runs
# apm.process_stream() over every inbound frame (livekit-agents 1.7.1,
# voice/room_io/types.py:69, _input.py:263). That is WebRTC gain processing
# rewriting the caller's audio before Gemini ever hears it — on a noisy phone
# line it pumps the level, and if this lane then scored differently from the
# others nobody could say whether that was the runtime or the AGC. Set
# VOICELAB_AGC=1 to measure the other half of that pair deliberately.
AGC = _env_flag("VOICELAB_AGC", "0")

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are a voice assistant on a phone call. Keep every reply to one or two "
    "short spoken sentences. Never mention that you are an AI model."
)
DEFAULT_GREETING = "Greet the caller in one short sentence and ask how you can help."


def _system_instruction() -> str:
    """Bare prompt, from a file if given so a lane run can be reproduced exactly."""
    path = _env("VOICELAB_SYSTEM_INSTRUCTION_FILE")
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return _env("VOICELAB_SYSTEM_INSTRUCTION") or DEFAULT_SYSTEM_INSTRUCTION


def _api_key() -> str:
    """GEMINI_API_KEY is voicelab's spelling; GOOGLE_API_KEY is the plugin's."""
    key = _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("set GEMINI_API_KEY (or GOOGLE_API_KEY) — see .env.example")
    return key


def _force_ipv4_if_asked() -> None:
    """OVH's IPv6 block makes Google answer 'User location is not supported'.

    Verified from the VM on 2026-08-18 (SETUP.md §45b): FAILED_PRECONDITION over
    IPv6, fine over IPv4. This lane is meant to run OFF the VM, so the shim is
    off by default; turn it on if you ever host the worker there. Patching
    socket.getaddrinfo after import is enough — asyncio's default resolver looks
    the symbol up at call time, it does not bind it at import.
    """
    if not _env_flag("VOICELAB_FORCE_IPV4", "0"):
        return
    original = socket.getaddrinfo

    def ipv4_first(*args: Any, **kwargs: Any) -> Any:
        results = original(*args, **kwargs)
        v4 = [r for r in results if r[0] == socket.AF_INET]
        return v4 or results

    socket.getaddrinfo = ipv4_first  # type: ignore[assignment]
    logger.info("VOICELAB_FORCE_IPV4=1 — resolving IPv4 first")


# --------------------------------------------------------------------------- #
# scorecard
# --------------------------------------------------------------------------- #


@dataclass
class _LocalScorecard:
    """Field-for-field stand-in for voicelab.harness.scorecard.Scorecard.

    Only used when the shared package is not installed in this lane's venv, so a
    LiveKit run still produces a JSON the bake-off can read. Durations are
    monotonic; wall time only appears as a stamp in to_dict().
    """

    lane: str
    carrier: str
    call_id: str | None = None
    greeting_ms: float | None = None
    responses_ms: list[float] = field(default_factory=list)
    barge_ins: list[dict[str, Any]] = field(default_factory=list)
    hangs: int = 0
    interruptions: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: float | None = None
    ended_at: float | None = None
    audio_in_bytes: int = 0
    audio_out_bytes: int = 0

    _pending_turn_end: float | None = None

    def mark_user_speech_end(self) -> None:
        self._pending_turn_end = time.monotonic()

    def mark_bot_audio_start(self) -> None:
        now = time.monotonic()
        if self._pending_turn_end is not None:
            self.responses_ms.append((now - self._pending_turn_end) * 1000.0)
            self._pending_turn_end = None
        elif self.greeting_ms is None and self.started_at is not None:
            self.greeting_ms = (now - self.started_at) * 1000.0

    def mark_hang(self) -> None:
        self.hangs += 1

    def _pct(self, q: float) -> float | None:
        if not self.responses_ms:
            return None
        ordered = sorted(self.responses_ms)
        idx = min(len(ordered) - 1, round(q * (len(ordered) - 1)))
        return ordered[idx]

    def p50(self) -> float | None:
        return self._pct(0.50)

    def p95(self) -> float | None:
        return self._pct(0.95)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane,
            "carrier": self.carrier,
            "call_id": self.call_id,
            "greeting_ms": self.greeting_ms,
            "responses_ms": list(self.responses_ms),
            "p50_ms": self.p50(),
            "p95_ms": self.p95(),
            "barge_ins": list(self.barge_ins),
            "hangs": self.hangs,
            "interruptions": self.interruptions,
            "errors": list(self.errors),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_s": (
                self.ended_at - self.started_at
                if self.started_at is not None and self.ended_at is not None
                else None
            ),
            "audio_in_bytes": self.audio_in_bytes,
            "audio_out_bytes": self.audio_out_bytes,
        }

    def write(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


try:
    # Shared with the bridge lanes when this venv has the voicelab package
    # linked (`uv sync --group scorecard`); the fallback above otherwise.
    from voicelab.harness.scorecard import Scorecard as _Scorecard  # type: ignore[import-untyped]

    SCORECARD_SOURCE = "voicelab.harness.scorecard"
except Exception:  # ImportError, or a half-built harness module
    _Scorecard = _LocalScorecard  # type: ignore[misc, assignment]
    SCORECARD_SOURCE = "lane-local fallback"


# --------------------------------------------------------------------------- #
# law #4 — a broken run must not look like a dead one
# --------------------------------------------------------------------------- #


class HangWatch:
    """Fires on_hang if the agent never starts speaking after we expected it to.

    A wrong audio format or a rejected config fails as a *silent* hang on every
    Gemini Live lane: zero events, no exception. Without this a broken run and a
    caller who simply said nothing produce identical scorecards. Timer-based, not
    task-based, because every AgentSession event callback is synchronous.
    """

    def __init__(self, timeout_s: float, on_hang: Any) -> None:
        self._timeout_s = timeout_s
        self._on_hang = on_hang
        self._handle: asyncio.TimerHandle | None = None
        self._label = ""

    def expect_response(self, label: str = "") -> None:
        self.got_response()
        self._label = label
        loop = asyncio.get_running_loop()
        self._handle = loop.call_later(self._timeout_s, self._fire)

    def got_response(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    def _fire(self) -> None:
        self._handle = None
        logger.error(
            "no model response within %.1fs after %s — silent hang (law #4)",
            self._timeout_s,
            self._label or "kick-off",
        )
        self._on_hang(self._label)


# --------------------------------------------------------------------------- #
# agent
# --------------------------------------------------------------------------- #


class BareAgent(Agent):
    """No tools, no handoffs — just the system instruction and an output tap."""

    def __init__(self, instructions: str, tools: list | None = None) -> None:
        super().__init__(instructions=instructions, tools=tools or [])
        self.audio_out_bytes = 0

    async def realtime_audio_output_node(
        self, audio: AsyncIterable[rtc.AudioFrame], model_settings: Any
    ) -> AsyncIterator[rtc.AudioFrame]:
        """Pass-through tap. The only place this lane can count model audio.

        Byte count is computed from the frame geometry rather than len(frame.data)
        because rtc.AudioFrame.data is a memoryview of int16 and its len() is
        samples on some SDK builds, bytes on others.
        """
        async for frame in audio:
            self.audio_out_bytes += frame.samples_per_channel * frame.num_channels * 2
            yield frame


def _build_gptlive_model(backend_instruction: str | None = None) -> Any:
    """Arm B: `gpt-live-1` with reasoning delegated to a Responses backend.

    The same topology as the Gemini arm on purpose: LiveKit owns the whole audio
    path, so neither arm has a resampler of ours anywhere near it. That matters
    because the bridge version of this lane did have one, on the input side, and
    it cost arm B both latency and turn-detection sanity.

    Why this is not symmetrical with `_build_model`, and must not be:

    * GPT-Live is **server-driven**. The LiveKit docs are explicit that no client
      event creates, cancels or truncates a response: the model starts and ends
      its own turns. `turn_detection="realtime_llm"` is therefore the only
      honest setting here, which happens to match the Gemini arm.
    * Voice and instructions **cannot change mid-session**; a change raises
      `RealtimeError`. Nothing in this lane tries.
    * Reasoning lives in `responses_options`, not in the voice prompt, per the
      prompt split this benchmark already uses.
    """
    live_prompt, backend_prompt = _prompt_pair()
    kwargs: dict[str, Any] = {
        "model": GPTLIVE_MODEL,
        "voice": GPTLIVE_VOICE,
        "delegation": "responses",
        "responses_options": {
            "model": GPTLIVE_BACKEND,
            "instructions": backend_instruction or backend_prompt,
        },
    }
    if key := _env("OPENAI_API_KEY"):
        kwargs["api_key"] = key
    logger.info(
        "gptlive: model=%s voice=%s backend=%s live_prompt=%d chars backend_prompt=%d chars",
        GPTLIVE_MODEL,
        GPTLIVE_VOICE,
        GPTLIVE_BACKEND,
        len(live_prompt),
        len(backend_instruction or backend_prompt),
    )
    return GPTLiveModel(**kwargs)


def _prompt_pair() -> tuple[str, str]:
    """(voice prompt, backend prompt) for the GPT-Live arm.

    Prefers two explicit files over splitting one instruction, because the split
    is only as good as the headings it is given. ``voicelab.bench.agent``'s
    ``gemini_instruction()`` emits no ``LANGUAGE:`` heading, so feeding its
    output to ``_split_instruction`` keeps paragraph one alone and silently drops
    the language rule -- which is how arm B greeted an English caller in
    Romanian. ``gptlive_live_prompt()`` already carries that rule, so write the
    two prompts to files and point these vars at them.

    Falls back to the heading split when only one instruction is supplied.
    """
    live_path = _env("VOICELAB_LIVE_PROMPT_FILE")
    backend_path = _env("VOICELAB_BACKEND_PROMPT_FILE")
    if live_path and backend_path:
        live = Path(live_path).read_text(encoding="utf-8").strip()
        backend = Path(backend_path).read_text(encoding="utf-8").strip()
        if live and backend:
            return live, backend
        raise RuntimeError(
            f"empty prompt file: live={live_path} ({len(live)} chars) "
            f"backend={backend_path} ({len(backend)} chars)"
        )
    return _split_instruction(_system_instruction())


def _split_instruction(instruction: str) -> tuple[str, str]:
    """(voice prompt, backend prompt), by section heading.

    Same rule as `voicelab.lanes.gptlive.split_instruction`, and here for the
    same measured reason: taking paragraph one only left the voice model without
    the LANGUAGE section, and it greeted an English caller in Romanian.
    """
    text = (instruction or "").strip()
    if not text:
        return "", ""
    paragraphs = text.split("\n\n")
    kept = [paragraphs[0].strip()]
    kept += [
        p.strip()
        for p in paragraphs[1:]
        if p.split("\n", 1)[0].strip().rstrip(":").upper() in LIVE_SECTIONS
    ]
    return "\n\n".join(kept), text


def _build_model() -> google.realtime.RealtimeModel:
    """The bake-off's model, configured to do as little as possible on the way."""
    kwargs: dict[str, Any] = {
        "model": MODEL,
        "api_key": _api_key(),
        "voice": VOICE,
        "instructions": _system_instruction(),
        # Pin activity coverage explicitly. This is an input setting, not a
        # guarantee about billed tokens; billing comes from observed usage.
        "realtime_input_config": genai_types.RealtimeInputConfig(
            turn_coverage=genai_types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
        ),
    }
    # Law #5: audio-only Live sessions hard-cap at 15 min and the socket recycles
    # ~10 min in. The plugin already sends a SessionResumptionConfig on every
    # connect and re-uses the server's handle, so this is belt and braces — it
    # only seeds the first handle. Set VOICELAB_SESSION_RESUMPTION=0 to measure
    # the lane without it.
    if _env_flag("VOICELAB_SESSION_RESUMPTION", "1"):
        kwargs["session_resumption"] = genai_types.SessionResumptionConfig()
    temperature = _env("VOICELAB_TEMPERATURE")
    if temperature:
        kwargs["temperature"] = float(temperature)
    # Deliberately NOT passing `language`: native-audio Live models auto-detect
    # and reject an explicit language code. Pin language in the prompt instead.
    return google.realtime.RealtimeModel(**kwargs)


def _build_session(model: Any) -> AgentSession:
    return AgentSession(
        llm=model,
        # THE bare-ness switch. If turn_detection is left unset the session
        # auto-selects, and a future version is free to slot LiveKit's own
        # turn-detector model in front of the turn loop — extra inference on
        # every turn, which is precisely what this bake-off is trying to rule
        # out as the cause of the chopping. "realtime_llm" means: Gemini's
        # server-side VAD decides turns, nobody else touches them.
        # apps/livekit-lab/agent.py does NOT set this, so our earlier LiveKit
        # test was not a bare runtime and its result does not transfer here.
        turn_handling=TurnHandlingOptions(turn_detection="realtime_llm"),
    )


@dataclass(frozen=True)
class RoomSetup:
    """What we asked RoomIO for, and what we actually got, for the scorecard."""

    options: Any
    input_rate: int
    agc: bool
    notes: tuple[str, ...] = ()


def _room_options() -> RoomSetup:
    """Pin RoomIO's inbound path: 16 kHz, no noise cancellation, no AGC.

    Built on EVERY run, including ROOM_INPUT_RATE=0. Omitting `room_options`
    entirely is not "the default rate with nothing else changed": RoomOptions'
    `get_audio_input_options()` falls back to a bare `AudioInputOptions()`, whose
    `auto_gain_control` is True. So the 24 kHz measurement has to be spelled out
    rather than left implicit, or it silently runs with WebRTC gain processing on
    the inbound frames and stops being comparable with the 16 kHz one.

    `options` is None only when this build of livekit-agents does not expose
    RoomOptions at all — we take its defaults and say so rather than fail the run.
    """
    try:
        from livekit.agents.voice.room_io import AudioInputOptions, RoomOptions
    except ImportError:
        return RoomSetup(
            options=None,
            input_rate=ROOMIO_DEFAULT_RATE,
            agc=True,
            notes=("RoomOptions unavailable; RoomIO left at its defaults (24 kHz, AGC ON)",),
        )

    rate = ROOM_INPUT_RATE or ROOMIO_DEFAULT_RATE
    kwargs: dict[str, Any] = {
        "sample_rate": rate,
        # noise_cancellation stays None: no Krisp, no BVC, nothing between the
        # caller's Opus and the model. Keep krisp_enabled false on the SIP trunk
        # too (lk/trunk.json) or LiveKit filters the audio before we see it.
        "noise_cancellation": None,
    }
    # Guarded because auto_gain_control is a 1.7-era field and this lane's floor
    # is `~=1.5`. A build without it cannot turn the APM off, and a run that is
    # not bare on the inbound path must say so in its own scorecard.
    if "auto_gain_control" in {f.name for f in dataclasses.fields(AudioInputOptions)}:
        kwargs["auto_gain_control"] = AGC
        agc = AGC
        notes: tuple[str, ...] = ()
    else:
        agc = True
        notes = ("AudioInputOptions has no auto_gain_control — inbound APM is ON, not bare",)
        logger.warning("this livekit-agents build cannot disable AGC — inbound path is not bare")
    return RoomSetup(
        options=RoomOptions(audio_input=AudioInputOptions(**kwargs)),
        input_rate=rate,
        agc=agc,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# law #3 — the model never speaks first
# --------------------------------------------------------------------------- #


def _greeting_nudge() -> str:
    """The realtime-input text that makes Gemini 3.x actually generate.

    Read with a raw os.getenv rather than _env() because whitespace is the whole
    point here: pipecat ships a bare space for this, and _env() strips.
    """
    return os.getenv("VOICELAB_GREETING_NUDGE") or " "


def _kick_off_greeting(agent: Agent, session: AgentSession, greeting: str) -> str:
    """Make the agent greet first on a model that refuses generate_reply().

    Two separate obstacles, and the second one is the one that bites.

    First: the Google plugin sets mutable_chat_context=False for any model whose
    name contains "3.1" (realtime_api.py:315, livekit-agents 1.7.1), and
    generate_reply() returns a failed future behind exactly that flag (:776). So
    the session-level greeting API is simply unavailable on our model.

    Second, and non-obvious: sending the LiveClientContent turn that
    generate_reply() would have sent is NOT enough. send_client_content is
    documented as seeding history only — "To send text updates during the
    conversation, use send_realtime_input instead" — and Gemini 3.x will happily
    absorb a turn_complete=True turn without running inference on it. Pipecat hit
    the same wall and works around it the same way: send_client_content(...,
    turn_complete=True) followed by send_realtime_input(text=" "), commented
    "Gemini 3.x wants turn_complete=True, but also won't run inference without a
    realtime input" (pipecat 1.8.1, services/google/gemini_live/llm.py:1671).
    Without that second frame the agent never speaks, and law #4's watchdog
    reports a silent hang that looks exactly like a wrong audio format — the one
    confusion this whole bake-off is built to avoid.

    The plugin's send task already routes LiveClientRealtimeInput.text to
    session.send_realtime_input(text=...) (realtime_api.py:1062), so the nudge
    needs no new plumbing.

    Returns the shape that was QUEUED. It is not evidence of success:
    _send_client_event() swallows everything except a closed channel, so nothing
    here can report a failure. Read lane_extra.greeting_confirmed (set from real
    model audio) or the scorecard's `hangs` for that.
    """
    mode = _env("VOICELAB_GREETING_MODE", "user").lower()
    try:
        rt = agent.realtime_llm_session
    except Exception as exc:
        logger.warning("no realtime session for the kick-off (%r), trying generate_reply()", exc)
        return _kick_off_via_generate_reply(session, greeting)

    if mode == "realtime":
        # No history seed at all: the instruction rides the realtime channel,
        # which is what the Live API docs point at for text during a session.
        # Use it if the seeded copy makes the model read the instruction aloud.
        rt._send_client_event(genai_types.LiveClientRealtimeInput(text=greeting))
        path = "realtime_input:greeting"
    else:
        if mode == "livekit":
            # The plugin's own shape: the instruction arrives as a *model* turn
            # and the user turn is a bare ".". Odd, but it is what LiveKit ships
            # inside generate_reply(instructions=...). Use it if the model reads
            # the plain user-turn wording aloud instead of acting on it.
            turns = [
                genai_types.Content(parts=[genai_types.Part(text=greeting)], role="model"),
                genai_types.Content(parts=[genai_types.Part(text=".")], role="user"),
            ]
        else:
            # Default: one user turn, identical to what the other three lanes
            # send through RealtimeRuntime.send_text(). Comparability wins.
            turns = [genai_types.Content(parts=[genai_types.Part(text=greeting)], role="user")]
        # Private, deliberately: it is the only path to a client turn that the
        # mutable_chat_context gate does not sit on. Pinned to the plugin's
        # 1.7.x internals — re-check on a major bump.
        rt._send_client_event(genai_types.LiveClientContent(turns=turns, turn_complete=True))
        # THE line that makes the model speak. Do not "simplify" it away.
        rt._send_client_event(genai_types.LiveClientRealtimeInput(text=_greeting_nudge()))
        path = f"client_content:{mode}+realtime_input"

    logger.info("greeting kick-off queued (%s) — queued, not confirmed", path)
    return path


def _kick_off_via_generate_reply(session: AgentSession, greeting: str) -> str:
    """Last resort, and only when the model actually supports it.

    Gated on the plugin's own capability flag rather than on try/except, because
    AgentSession.generate_reply() returns a SpeechHandle and never raises: on a
    3.1 model it logs a warning, the refusal lands on an inner future, and a bare
    try/except would report a greeting that was never generated.
    """
    caps = getattr(getattr(session, "llm", None), "capabilities", None)
    if not getattr(caps, "mutable_chat_context", False):
        logger.error(
            "model refuses generate_reply() and there is no realtime session — "
            "the caller must speak first"
        )
        return "none"
    session.generate_reply(instructions=greeting)
    logger.info("greeting kick-off queued via session.generate_reply()")
    return "generate_reply"


# --------------------------------------------------------------------------- #
# entrypoint
# --------------------------------------------------------------------------- #


async def entrypoint(ctx: JobContext) -> None:
    _force_ipv4_if_asked()

    metadata = json.loads(ctx.job.metadata or "{}")
    provider = metadata.get("provider", PROVIDER)
    if provider not in {"gemini", "gptlive"}:
        raise ValueError("Unsupported benchmark provider")
    is_caller = metadata.get("role") == "caller"
    benchmark = None
    if _env_flag("VOICELAB_BENCHMARK", "0"):
        from benchmark_support import BenchmarkContext

        benchmark = BenchmarkContext(
            metadata.get("scenario", "loading-dock"),
            int(metadata.get("seed", 41)),
            metadata.get("language", "ro"),
        )

    sc = _Scorecard(lane=LANE, carrier=CARRIER)
    sc.started_at = time.monotonic()
    sc.call_id = ctx.room.name
    extra: dict[str, Any] = {
        "model": GPTLIVE_MODEL if provider == "gptlive" else MODEL,
        "voice": GPTLIVE_VOICE if provider == "gptlive" else VOICE,
        "backend_model": GPTLIVE_BACKEND if provider == "gptlive" else None,
        "agent_name": AGENT_NAME,
        "room": ctx.room.name,
        "job_id": getattr(ctx.job, "id", None),
        "scorecard_source": SCORECARD_SOURCE,
        "provider": provider,
        "role": "caller" if is_caller else "agent",
        "run_id": metadata.get("run_id"),
        "usage_events": [],
        "cost": {"amount": None, "status": "requires_provider_billing_reconciliation"},
        "turn_detection": "realtime_llm",
        "room_input_rate": ROOM_INPUT_RATE or ROOMIO_DEFAULT_RATE,
        # Part of "bare", and a confound if it is ever on without being recorded:
        # AGC means WebRTC gain processing rewrites inbound frames before Gemini.
        "auto_gain_control": AGC,
        # What was QUEUED, not what worked — _send_client_event cannot fail.
        "greeting_path": None,
        "greeting_confirmed": None,
        "wall_started_at": time.time(),
        "transcript": [],
        # Honest gap: LiveKit's RoomIO feeds the realtime session directly, so
        # there is no tap for inbound PCM that does not steal frames from it.
        # audio_out_bytes is real (counted in BareAgent); audio_in_bytes is not.
        "audio_in_bytes_measured": False,
        "notes": [],
    }

    await ctx.connect()

    # Caller identity, when a real phone call put us here. Room name alone is
    # enough to join scorecards to LiveKit logs; sip.callID joins them to Twilio.
    def _capture_sip(participant: rtc.RemoteParticipant) -> None:
        attrs = dict(participant.attributes or {})
        sip = {k: v for k, v in attrs.items() if k.startswith("sip.")}
        if sip:
            extra["sip"] = sip
            sc.call_id = sip.get("sip.callID") or sc.call_id

    for p in ctx.room.remote_participants.values():
        _capture_sip(p)
    ctx.room.on("participant_connected", _capture_sip)

    # Greet a caller who is actually there. Without this the kick-off can fire
    # into an empty room and the first thing the caller hears is the tail of the
    # greeting. Console mode has no remote participant — that timeout is normal.
    if not ctx.room.remote_participants:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(ctx.wait_for_participant(), timeout=PARTICIPANT_WAIT_S)

    if benchmark:
        expected = _env("BENCH_CONTROL_TOKEN")
        for participant in ctx.room.remote_participants.values():
            supplied = participant.attributes.get("bench.control", "")
            if expected and hmac.compare_digest(supplied, expected):
                is_caller = True
                provider = metadata.get("caller_provider", "gemini")
                break
        # Never retain the control token in scorecards.
        extra["role"] = "caller" if is_caller else "agent"
        extra["provider"] = provider
        extra["model"] = GPTLIVE_MODEL if provider == "gptlive" else MODEL
        extra["voice"] = GPTLIVE_VOICE if provider == "gptlive" else VOICE
        extra["backend_model"] = GPTLIVE_BACKEND if provider == "gptlive" else None

    is_gptlive = provider == "gptlive"
    prompts = benchmark.prompts() if benchmark else None
    backend_instruction = prompts[2] if prompts else None
    if is_caller and benchmark:
        backend_instruction = benchmark.call.caller_prompt
    model = _build_gptlive_model(backend_instruction) if is_gptlive else _build_model()
    session = _build_session(model)
    # The VOICE prompt. On GPT-Live the procedure lives in responses_options and
    # only conversational behaviour belongs here; on Gemini the model reasons
    # itself, so it gets the whole instruction.
    instruction = _prompt_pair()[0] if is_gptlive else _system_instruction()
    if prompts:
        instruction = prompts[1] if is_gptlive else prompts[0]
    if is_caller and benchmark:
        instruction = benchmark.call.caller_prompt
    agent = BareAgent(instruction, benchmark.tools() if benchmark and not is_caller else [])
    extra["instruction_sha256"] = hashlib.sha256(instruction.encode()).hexdigest()
    extra["backend_instruction_sha256"] = (
        hashlib.sha256(backend_instruction.encode()).hexdigest() if backend_instruction else None
    )

    @session.on("session_usage_updated")
    def _usage(ev: Any) -> None:
        # This is a cumulative snapshot; replace it, never sum snapshots.
        from benchmark_support import usage_snapshot

        extra["session_usage"] = usage_snapshot(ev.usage)

    @session.on("metrics_collected")
    def _metrics(ev: Any) -> None:
        metric = ev.metrics
        value = metric.model_dump() if hasattr(metric, "model_dump") else dataclasses.asdict(metric)
        extra["usage_events"].append(value)

    state: dict[str, Any] = {
        "agent_speaking": False,
        "first_audio_at": None,
        "kickoff_at": None,
        # True once the caller has spoken with the agent still silent. That is the
        # difference between "the greeting worked" and "the caller rescued it".
        "user_spoke_first": False,
    }

    def _on_hang(_label: str) -> None:
        sc.mark_hang()

    watchdog = HangWatch(WATCHDOG_S, _on_hang)

    @session.on("agent_state_changed")
    def _agent_state(ev: Any) -> None:
        if ev.new_state == "speaking":
            state["agent_speaking"] = True
            if state["first_audio_at"] is None:
                state["first_audio_at"] = time.monotonic()
            watchdog.got_response()
            sc.mark_bot_audio_start()
        elif ev.old_state == "speaking":
            state["agent_speaking"] = False

    @session.on("user_state_changed")
    def _user_state(ev: Any) -> None:
        if ev.new_state == "speaking" and state["first_audio_at"] is None:
            state["user_spoke_first"] = True
        if ev.new_state == "listening" and ev.old_state == "speaking":
            sc.mark_user_speech_end()
            watchdog.expect_response("user turn end")
        elif ev.new_state == "speaking" and state["agent_speaking"]:
            # Barge-in. On this lane LiveKit owns both flushes law #2 asks for
            # (it drops its own queued playout and stops the published track);
            # we only get to observe that it happened.
            sc.interruptions += 1
            sc.barge_ins.append(
                {
                    "t_ms": (time.monotonic() - (sc.started_at or time.monotonic())) * 1000.0,
                    "source": "user_state_changed",
                }
            )

    @session.on("conversation_item_added")
    def _item(ev: Any) -> None:
        role = getattr(ev.item, "role", None)
        text = getattr(ev.item, "text_content", None)
        if role and text:
            extra["transcript"].append({"role": role, "text": text})

    @session.on("error")
    def _error(ev: Any) -> None:
        sc.errors.append(repr(getattr(ev, "error", ev)))

    @session.on("close")
    def _close(ev: Any) -> None:
        sc.ended_at = time.monotonic()
        extra["close_reason"] = str(getattr(ev, "reason", None))

    room = _room_options()
    # Report what RoomIO ended up with, not what we asked for — a build that
    # cannot disable AGC still produces a scorecard, it just admits the confound.
    extra["room_input_rate"] = room.input_rate
    extra["auto_gain_control"] = room.agc
    extra["notes"].extend(room.notes)
    start_kwargs: dict[str, Any] = {"room": ctx.room}
    if room.options is not None:
        start_kwargs["room_options"] = room.options
    await session.start(agent, **start_kwargs)

    greeting = _env("VOICELAB_GREETING") or DEFAULT_GREETING
    if benchmark:
        greeting = (
            "off"
            if is_caller
            else (
                "Greet briefly in Romanian as Nora, a demo assistant; ask how you can help."
                if benchmark.call.world.language == "ro"
                else "Greet briefly in English as the demo assistant; ask how you can help."
            )
        )
    if greeting.lower() not in {"", "none", "off"}:
        state["kickoff_at"] = time.monotonic()
        # GPT-Live is server-driven and supports the session-level greeting API,
        # which the Gemini 3.x plugin refuses (see _kick_off_greeting). The docs
        # give it a 10 s budget to start speaking.
        if is_gptlive:
            session.generate_reply(instructions=greeting)
            extra["greeting_path"] = "generate_reply"
            logger.info("gptlive: greeting queued via session.generate_reply()")
        else:
            extra["greeting_path"] = _kick_off_greeting(agent, session, greeting)
        watchdog.expect_response("greeting kick-off")
    else:
        extra["greeting_path"] = "disabled"

    written = False

    def _write_scorecard() -> None:
        nonlocal written
        if written:
            return
        written = True
        watchdog.got_response()
        if sc.ended_at is None:
            sc.ended_at = time.monotonic()
        sc.audio_out_bytes = agent.audio_out_bytes

        # Two different clocks, and the difference matters when comparing lanes.
        # started_at is job start, so first audio measured from it also contains
        # LiveKit's dispatch and room-join time — real latency for a caller, but
        # not the model's. The kick-off stamp isolates the model. Record both,
        # and if the Scorecard left greeting_ms empty (it has no user turn to
        # pair the first bot audio with), fill it with the model-only number.
        first_audio = state["first_audio_at"]
        kickoff = state["kickoff_at"]
        # The only honest answer to "did the greeting work": model audio arrived
        # after the kick-off and before the caller ever spoke. greeting_path only
        # says what we queued — the plugin's send path cannot report a failure.
        if kickoff is not None:
            extra["greeting_confirmed"] = first_audio is not None and not state["user_spoke_first"]
        if first_audio is not None:
            if sc.started_at is not None:
                extra["first_audio_from_job_start_ms"] = (first_audio - sc.started_at) * 1000.0
            if kickoff is not None:
                extra["greeting_ms_from_kickoff"] = (first_audio - kickoff) * 1000.0
                if sc.greeting_ms is None:
                    sc.greeting_ms = extra["greeting_ms_from_kickoff"]

        payload = sc.to_dict()
        if benchmark:
            from benchmark_support import usage_snapshot

            extra["session_usage"] = usage_snapshot(session.usage)
        if benchmark:
            extra["benchmark"] = (
                benchmark.result()
                if not is_caller
                else {
                    "scenario": benchmark.name,
                    "seed": benchmark.call.world.seed,
                    "caller_prompt": benchmark.call.caller_prompt,
                }
            )
        payload["lane_extra"] = extra
        SCORECARD_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{LANE}-{CARRIER}-{ctx.room.name}-{int(time.time())}.json"
        path = SCORECARD_DIR / name
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        logger.info("scorecard -> %s", path)
        logger.info("BENCH_RESULT %s", json.dumps(payload, default=str))

    # Two triggers on purpose. `close` covers the caller hanging up mid-job;
    # the shutdown callback covers Ctrl+C in console mode and a worker drain,
    # where no close event ever arrives. `written` makes the second one a no-op.
    @session.on("close")
    def _close_write(_ev: Any) -> None:
        _write_scorecard()

    async def _on_shutdown() -> None:
        _write_scorecard()

    ctx.add_shutdown_callback(_on_shutdown)

    if benchmark:

        async def hard_limit() -> None:
            await asyncio.sleep(min(float(metadata.get("max_seconds", 180)) + 30, 240))
            await session.aclose()
            ctx.shutdown(reason="benchmark duration limit")

        limit_task = asyncio.create_task(hard_limit())

        async def cancel_limit() -> None:
            limit_task.cancel()

        ctx.add_shutdown_callback(cancel_limit)


if __name__ == "__main__":
    agents.cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            # Explicit dispatch: with agent_name set, LiveKit hands this worker a
            # room ONLY when something asks for it by name — which is what
            # lk/dispatch.json's roomConfig.agents does. The flip side is that
            # the agents playground will not auto-dispatch it; see README.
            agent_name=AGENT_NAME,
            port=int(_env("VOICELAB_WORKER_PORT", "8098")),
        )
    )
