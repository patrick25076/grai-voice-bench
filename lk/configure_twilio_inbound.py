"""Twilio Elastic SIP origination needs IP authentication, not digest auth.

Sources verified 2026-09-12:
https://docs.livekit.io/telephony/accepting-calls/inbound-trunk/
https://www.twilio.com/docs/sip-trunking/ip-addresses
"""

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from livekit import api

SIGNALING_IPS = (
    "54.172.60.0/30",
    "54.244.51.0/30",
    "54.171.127.192/30",
    "35.156.191.128/30",
    "54.65.63.192/30",
    "54.169.127.128/30",
    "54.252.254.64/30",
    "177.71.206.192/30",
)


async def main(args):
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.deploy")
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    async with api.LiveKitAPI() as client:
        rows = await client.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())
        trunk = next(t for t in rows.items if t.sip_trunk_id == args.trunk)
        if list(trunk.numbers) != [args.number]:
            raise ValueError("Refusing a trunk containing anything except the supplied test number")
        print("Replace unsupported digest authentication with Twilio signaling IP allowlist")
        if not args.apply:
            return
        args.rollback.parent.mkdir(parents=True, exist_ok=True)
        with args.rollback.open("xb") as file:
            file.write(trunk.SerializeToString())
        trunk.auth_username = ""
        trunk.auth_password = ""
        trunk.allowed_addresses.clear()
        trunk.allowed_addresses.extend(SIGNALING_IPS)
        await client.sip.update_inbound_trunk(args.trunk, trunk)
        print("Updated only the dedicated test trunk; original saved privately")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trunk", required=True)
    parser.add_argument("--number", required=True)
    parser.add_argument("--rollback", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args()))
