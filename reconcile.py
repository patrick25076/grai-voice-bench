"""Refresh only carrier prices for calls already recorded in this pilot."""

import argparse
import json
from pathlib import Path

import httpx
from dotenv import dotenv_values


def main(root: Path, env_path: Path):
    env = dotenv_values(env_path)
    sid = env["TWILIO_ACCOUNT_SID"]
    base = f"https://api.dublin.ie1.twilio.com/2010-04-01/Accounts/{sid}"
    with httpx.Client(auth=(sid, env["TWILIO_AUTH_TOKEN_IE1"]), timeout=30) as client:
        for path in root.glob("*/run.json"):
            run = json.loads(path.read_text(encoding="utf-8"))
            for kind in ("calls", "recordings"):
                resource = "Calls" if kind == "calls" else "Recordings"
                for item in run[kind]:
                    response = client.get(base + f"/{resource}/{item['sid']}.json")
                    response.raise_for_status()
                    remote = response.json()
                    for key in ("price", "price_unit", "status", "duration"):
                        item[key] = remote.get(key)
            path.write_text(json.dumps(run, indent=2), encoding="utf-8")
            print(path.parent.name, "carrier billing fields refreshed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--env", type=Path, default=Path(".env.twilio"))
    args = parser.parse_args()
    main(args.root, args.env)
