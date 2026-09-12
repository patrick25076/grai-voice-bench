"""Join downloaded worker evidence to carrier runs; retain incomplete evidence."""

import argparse
import json
from pathlib import Path

from costs import estimate_usage


def main(root):
    cards = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in (root / "worker-scorecards").glob("*.json")
    ]
    summary = []
    for path in sorted(root.glob("*/run.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        run_id = run["setup"]["run_id"]
        related = [card for card in cards if card["lane_extra"].get("run_id") == run_id]
        callers = [
            card
            for card in related
            if card["lane_extra"].get("role") == "caller"
            and card["lane_extra"].get("sip", {}).get("sip.twilio.callSid") == run.get("call_id")
        ]
        expected_phone = (
            callers[0]["lane_extra"].get("sip", {}).get("sip.phoneNumber")
            if len(callers) == 1
            else None
        )
        targets = [
            card
            for card in related
            if card["lane_extra"].get("role") == "agent"
            and expected_phone
            and card["lane_extra"].get("sip", {}).get("sip.phoneNumber") == expected_phone
        ]
        if len(callers) > 1 or len(targets) > 1:
            raise ValueError(
                f"Ambiguous worker evidence for {run_id}; do not choose a scorecard silently"
            )
        related = callers + targets
        evidence = {
            "run_id": run_id,
            "provider": run["setup"]["provider"],
            "status": run["status"],
            "roles": {},
        }
        for card in related:
            extra = card["lane_extra"]
            role = extra["role"]
            (path.parent / f"{role}-evidence.json").write_text(
                json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            evidence["roles"][role] = {
                "model": extra["model"],
                "duration_s": card["duration_s"],
                "grade": extra["benchmark"].get("grade"),
                "tools": extra["benchmark"].get("tool_executions", []),
                "cost_estimate": estimate_usage(extra.get("session_usage", {})),
                "sdk_watchdog_flags": card["hangs"],
                "runtime_errors": card["errors"],
                "transcript_items": len(extra["transcript"]),
            }
        reported = run["calls"] + run["recordings"]
        priced = [
            abs(float(row["price"]))
            for row in reported
            if row.get("price") is not None
            and (row.get("price_unit") == "USD" or float(row["price"]) == 0)
        ]
        evidence["known_carrier_cost_usd"] = sum(priced) if priced else None
        evidence["pending_carrier_prices"] = sum(row.get("price") is None for row in reported)
        evidence["unreconciled_costs"] = (
            []
            if any(
                row.get("component") == "inbound_target_trunk" and row.get("price") is not None
                for row in run["calls"]
            )
            else ["inbound Elastic SIP trunk leg"]
        ) + [
            "LiveKit SIP and media",
            "allocated VM hosting",
            "provider invoice and any usage not present in final SDK snapshot",
        ]
        summary.append(evidence)
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            [
                {
                    k: row[k]
                    for k in (
                        "run_id",
                        "provider",
                        "status",
                        "known_carrier_cost_usd",
                        "pending_carrier_prices",
                    )
                }
                for row in summary
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    main(parser.parse_args().root)
