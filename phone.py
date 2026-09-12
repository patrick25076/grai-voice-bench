"""One real PSTN call: AI caller -> Twilio Dial Number -> AI target.

Requires a dedicated inbound trunk and dispatch rule, both supplied explicitly.
The caller is connected over SIP first so the target greeting is not clipped.
Call charges can settle later: reservations are not refunded automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

import httpx
from dotenv import load_dotenv
from livekit import api

TERMINAL = {"completed", "failed", "busy", "no-answer", "canceled"}


@contextmanager
def session_lock(ledger: Path):
    """Serialize callers sharing a ledger for the entire routing transaction."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    lock = ledger.with_suffix(".lock")
    handle = lock.open("x")
    try:
        with handle:
            yield
    finally:
        lock.unlink()


async def run(args):
    from voicelab.bench.suite import scenario

    scenario(args.scenario, args.seed, args.language)
    if not 10 <= args.seconds <= 180:
        raise ValueError("Call duration must be 10..180 seconds")
    if (
        not math.isfinite(args.reserve_eur)
        or not math.isfinite(args.cap_eur)
        or args.reserve_eur < 2
        or not 0 < args.cap_eur <= 25
    ):
        raise ValueError("Reserve at least EUR 2/call; use a finite cap up to EUR 25")
    with session_lock(args.ledger.resolve()):
        await _run_locked(args)


async def _run_locked(args):
    load_dotenv(args.env)
    load_dotenv(args.carrier_env)
    load_dotenv(Path(__file__).resolve().parent / ".env")
    required = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN_IE1", "BENCH_CONTROL_TOKEN"]
    if any(not os.getenv(key) for key in required):
        raise ValueError("Missing required environment names: " + ", ".join(required))
    args.output.mkdir(parents=True, exist_ok=False)
    # The caller holds the shared ledger lock until routing is restored.
    ledger = args.ledger.resolve()
    budget = (
        json.loads(ledger.read_text())
        if ledger.exists()
        else {"cap_eur": args.cap_eur, "reserved_eur": 0, "calls": []}
    )
    if not all(math.isfinite(budget[key]) for key in ("cap_eur", "reserved_eur")):
        raise ValueError("Ledger contains a non-finite budget")
    if budget["reserved_eur"] + args.reserve_eur > min(args.cap_eur, budget["cap_eur"]):
        raise ValueError("Budget reservation would exceed the session cap")
    budget["reserved_eur"] += args.reserve_eur
    budget["calls"].append({"output": str(args.output), "reserved_eur": args.reserve_eur})
    ledger.write_text(json.dumps(budget, indent=2))

    metadata = {
        "provider": args.provider,
        "caller_provider": args.caller_provider,
        "scenario": args.scenario,
        "seed": args.seed,
        "language": args.language,
        "max_seconds": args.seconds,
        "run_id": args.output.name,
    }
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    base = f"https://api.dublin.ie1.twilio.com/2010-04-01/Accounts/{sid}"
    result = {
        "setup": metadata,
        "transport": "twilio-ie1-pstn-livekit",
        "cost_eur": None,
        "reserved_eur": args.reserve_eur,
        "calls": [],
        "recordings": [],
        "status": "starting",
    }
    async with (
        api.LiveKitAPI() as lk,
        httpx.AsyncClient(
            auth=(sid, os.environ["TWILIO_AUTH_TOKEN_IE1"]),
            timeout=30,
        ) as carrier,
    ):
        trunks = await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())
        trunk = next(t for t in trunks.items if t.sip_trunk_id == args.trunk)
        if list(trunk.numbers) != [args.target]:
            raise ValueError("Trunk must contain only the explicitly supplied benchmark target")
        rules = await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())
        rule = next(r for r in rules.items if r.sip_dispatch_rule_id == args.rule)
        if list(rule.trunk_ids) != [args.trunk]:
            raise ValueError("Dispatch rule must be scoped to the dedicated benchmark trunk")
        original_trunk = api.SIPInboundTrunkInfo()
        original_trunk.CopyFrom(trunk)
        original_rule = api.SIPDispatchRuleInfo()
        original_rule.CopyFrom(rule)
        # Durable private rollback contains routing configuration, not credentials in logs.
        (args.output / "rollback-trunk.pb").write_bytes(original_trunk.SerializeToString())
        (args.output / "rollback-rule.pb").write_bytes(original_rule.SerializeToString())
        call_id = None
        try:
            trunk.headers_to_attributes["X-Grai-Bench-Control"] = "bench.control"
            await lk.sip.update_inbound_trunk(args.trunk, trunk)
            rule.room_config.agents.clear()
            rule.room_config.agents.add(agent_name=args.agent, metadata=json.dumps(metadata))
            await lk.sip.update_dispatch_rule(args.rule, rule)
            uri = f"sip:{args.target}@{args.sip_host};transport=tcp?X-Grai-Bench-Control=" + quote(
                os.environ["BENCH_CONTROL_TOKEN"], safe=""
            )
            twiml = (
                f'<Response><Dial callerId="{escape(args.caller_id)}" '
                f'timeLimit="{args.seconds}" timeout="25" record="record-from-answer-dual">'
                f"<Number>{escape(args.target)}</Number></Dial><Hangup/></Response>"
            )
            call_data = {
                "To": uri,
                "From": args.caller_id,
                "Twiml": twiml,
                "Timeout": "25",
                "TimeLimit": str(args.seconds + 30),
            }
            if trunk.auth_username:
                if not os.getenv("SIP_AUTH_PASSWORD"):
                    raise ValueError("SIP_AUTH_PASSWORD is required for this trunk")
                call_data["SipAuthUsername"] = os.getenv("SIP_AUTH_USERNAME", trunk.auth_username)
                call_data["SipAuthPassword"] = os.environ["SIP_AUTH_PASSWORD"]
            response = await carrier.post(base + "/Calls.json", data=call_data)
            response.raise_for_status()
            call_id = response.json()["sid"]
            result["call_id"] = call_id
            print(json.dumps({"call_id": call_id, "status": "started"}), flush=True)
            deadline = time.monotonic() + args.seconds + 55
            while time.monotonic() < deadline:
                await asyncio.sleep(5)
                response = await carrier.get(base + f"/Calls/{call_id}.json")
                response.raise_for_status()
                row = response.json()
                result["status"] = row["status"]
                print(
                    json.dumps({"status": row["status"], "duration": row.get("duration")}),
                    flush=True,
                )
                if row["status"] in TERMINAL:
                    break
            else:
                result["status"] = "local_timeout"
        finally:
            result["cleanup_errors"] = []
            try:
                if call_id:
                    response = await carrier.post(
                        base + f"/Calls/{call_id}.json", data={"Status": "completed"}
                    )
                    result["hangup_http_status"] = response.status_code
                    response.raise_for_status()
            except Exception as exc:
                result["cleanup_errors"].append(f"hangup: {type(exc).__name__}")
            # Attempt both restorations even if carrier hangup or one update fails.
            for name, restore in (
                ("rule", lambda: lk.sip.update_dispatch_rule(args.rule, original_rule)),
                ("trunk", lambda: lk.sip.update_inbound_trunk(args.trunk, original_trunk)),
            ):
                try:
                    await restore()
                except Exception as exc:
                    result["cleanup_errors"].append(f"restore {name}: {type(exc).__name__}")
            (args.output / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        if call_id:
            await asyncio.sleep(5)
            response = await carrier.get(base + "/Calls.json", params={"ParentCallSid": call_id})
            response.raise_for_status()
            ids = [call_id] + [c["sid"] for c in response.json()["calls"]]
            for current in ids:
                row = (await carrier.get(base + f"/Calls/{current}.json")).json()
                result["calls"].append(
                    {k: row.get(k) for k in ["sid", "status", "duration", "price", "price_unit"]}
                )
                response = await carrier.get(base + f"/Calls/{current}/Recordings.json")
                response.raise_for_status()
                for recording in response.json().get("recordings", []):
                    recording_id = recording["sid"]
                    if recording_id in [r["sid"] for r in result["recordings"]]:
                        continue
                    data = await carrier.get(
                        base + f"/Recordings/{recording_id}.wav", params={"RequestedChannels": "2"}
                    )
                    if data.is_success:
                        (args.output / f"{recording_id}.wav").write_bytes(data.content)
                    result["recordings"].append(
                        {
                            k: recording.get(k)
                            for k in [
                                "sid",
                                "channels",
                                "duration",
                                "status",
                                "price",
                                "price_unit",
                            ]
                        }
                    )
            (args.output / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("target", "caller-id", "sip-host", "trunk", "rule", "agent"):
        p.add_argument("--" + key, required=True)
    p.add_argument("--env", type=Path, default=Path(".env"))
    p.add_argument("--carrier-env", type=Path, default=Path(".env.twilio"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--ledger", type=Path, required=True)
    p.add_argument("--provider", choices=["gemini", "gptlive"], required=True)
    p.add_argument("--caller-provider", choices=["gemini", "gptlive"], default="gemini")
    p.add_argument("--scenario", default="loading-dock")
    p.add_argument("--language", choices=["en", "ro"], default="ro")
    p.add_argument("--seed", type=int, default=41)
    p.add_argument("--seconds", type=int, default=120)
    p.add_argument("--reserve-eur", type=float, default=3)
    p.add_argument("--cap-eur", type=float, default=20)
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
