"""flop-trading: run the fleet in the Close Call contest (close-1).

    python -m flop_trading check              # roster and keys load and match; no network
    python -m flop_trading run                # register, then trade until the lock (LIVE: posts to technocore.chat)
    python -m flop_trading run --dry-run      # read everything live, sign everything, post nothing
    python -m flop_trading run --demo 20      # dry run with 20 throwaway keys instead of the roster
    python -m flop_trading status             # counts from the state database
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys

from .config import Config
from .fleet import Fleet, load_roster, setup_logging
from .keys import Key
from .store import Store

log = logging.getLogger("flop_trading")


def demo_roster(cfg: Config, count: int) -> Config:
    """Throwaway keys under state/demo/, so a dry run never touches the real keys."""
    base = cfg.state_dir / "demo"
    roster = base / "roster.json"
    entries = json.loads(roster.read_text()) if roster.exists() else []
    while len(entries) < count:
        nick = f"demo-{len(entries):03d}"
        key = Key.generate(base / "keys" / f"{nick}.pem")
        entries.append({"nick": nick, "did": key.did, "tier": "weak"})
    roster.write_text(json.dumps(entries, indent=1))
    return dataclasses.replace(cfg, roster=roster, keys_dir=base / "keys", max_agents=count)


def main() -> int:
    parser = argparse.ArgumentParser(prog="flop_trading", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--dry-run", action="store_true", help="post nothing")
    run.add_argument("--demo", type=int, metavar="N", help="dry run with N throwaway keys")
    run.add_argument("-v", "--verbose", action="store_true")
    sub.add_parser("check")
    sub.add_parser("status")
    args = parser.parse_args()
    cfg = Config.load()

    if args.cmd == "status":
        for name in ("fleet.sqlite", "dry-run.sqlite"):
            path = cfg.state_dir / name
            if path.exists():
                print(name, json.dumps(Store(path).summary(), indent=1))
        done = cfg.state_dir / "DONE"
        if done.exists():
            print("DONE:", done.read_text().strip())
        return 0

    if args.cmd == "check":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        roster = load_roster(cfg)
        total = len(json.loads(cfg.roster.read_text()))
        print(f"{len(roster)} of {total} roster agents have a matching key in {cfg.keys_dir}")
        return 0 if roster else 1

    if (cfg.state_dir / "DONE").exists() and not (args.dry_run or args.demo):
        print("state/DONE exists: the contest is over for this fleet. Delete it to run again.")
        return 0
    if args.demo:
        cfg = demo_roster(cfg, args.demo)
    dry = bool(args.dry_run or args.demo)
    setup_logging(cfg.state_dir, args.verbose)
    roster = load_roster(cfg)
    if not roster:
        log.error("no agents with keys: check FLOP_ROSTER and FLOP_KEYS_DIR")
        return 1
    try:
        Fleet(cfg, roster, dry_run=dry).run()
    except KeyboardInterrupt:
        log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
