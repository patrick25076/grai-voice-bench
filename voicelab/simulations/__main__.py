"""Offline fixture demos, tool-trace replay and balanced study planning."""

import argparse
import asyncio
import json
from pathlib import Path

from .cases import CASES, SimulationCase
from .runner import reference_actions, replay, study_plan, write_viewer


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["demo", "replay", "plan"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=["en", "ro"], default="ro")
    parser.add_argument("--case", choices=tuple(CASES), default="sim-amend-quantity")
    parser.add_argument("--script", type=Path)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260912)
    args = parser.parse_args()
    if args.command == "plan":
        data = study_plan(repetitions=args.repetitions, language=args.language, seed=args.seed)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        print(
            f"Planned {data['call_count']} calls; none executed. Budget and setup must be reviewed before dialing."
        )
        return
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    if args.command == "replay":
        if not args.script:
            parser.error("replay requires --script (JSON list of tool/arguments objects)")
        items = json.loads(args.script.read_text(encoding="utf-8"))
        case = SimulationCase(args.case, args.seed, args.language)
        rows.append(
            {
                "trace": "imported tool trace",
                **await replay(case, [(a["tool"], a["arguments"]) for a in items]),
            }
        )
    else:
        for name in CASES:
            for broken in (False, True):
                case = SimulationCase(name, args.seed, args.language)
                actions = reference_actions(case)
                if broken:
                    if name == "sim-amend-quantity":
                        # Correct final quantity through the wrong lifecycle: grader must reject.
                        actions = [("record_order", {**actions[0][1], "quantity_kg": 250})]
                    else:
                        actions = []
                rows.append(
                    {
                        "trace": "deliberately broken" if broken else "reference script",
                        **await replay(case, actions),
                    }
                )
    (args.output / "results.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_viewer(args.output / "index.html", rows)
    print(args.output / "index.html")


if __name__ == "__main__":
    asyncio.run(main())
