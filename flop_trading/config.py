"""Settings from the environment, or from a `.env` file in the app directory (KEY=value lines)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def _path(name: str, default: str) -> Path:
    path = Path(os.environ.get(name, default)).expanduser()
    return path if path.is_absolute() else APP_DIR / path


@dataclass(frozen=True)
class Config:
    roster: Path                # roster.json: [{"nick", "did", "tier", ...}]
    keys_dir: Path              # <nick>.pem for each roster entry
    state_dir: Path             # SQLite state, logs, pid file
    base_url: str
    room: str                   # where we register, offer and post trades
    referee_did: str
    lock_sweep: int
    max_agents: int             # 0 = the whole roster
    writes_per_minute: int
    reads_per_minute: int
    stream_poll_seconds: float  # close1 moves ~60 msg/s and a read returns the newest 200, so poll often
    agent_interval_minutes: float
    qty_min: Decimal
    qty_max: Decimal
    max_position: Decimal
    offer_edge: Decimal         # how much better than the mid our offers are for the taker
    offer_sweeps: int           # an offer stays valid for this many sweeps after the next one
    take_slip: Decimal          # accept others' offers up to this much worse than the mid
    max_take_qty: Decimal
    takes_per_minute: int

    @classmethod
    def load(cls) -> "Config":
        _load_dotenv(APP_DIR / ".env")
        env = os.environ.get
        return cls(
            roster=_path("FLOP_ROSTER", "roster.json"),
            keys_dir=_path("FLOP_KEYS_DIR", "keys"),
            state_dir=_path("FLOP_STATE_DIR", "state"),
            base_url=env("FLOP_BASE_URL", "https://technocore.chat"),
            room=env("FLOP_ROOM", "close1"),
            referee_did=env("FLOP_REFEREE_DID", "did:key:z6MkowHQwsx9xr84WbWN3YCnKutyBnBXkT1ChKY4uEAAMzte"),
            lock_sweep=int(env("FLOP_LOCK_SWEEP", "2556")),
            max_agents=int(env("FLOP_MAX_AGENTS", "0")),
            writes_per_minute=int(env("FLOP_WRITES_PER_MINUTE", "100")),
            reads_per_minute=int(env("FLOP_READS_PER_MINUTE", "300")),
            stream_poll_seconds=float(env("FLOP_STREAM_POLL_SECONDS", "2")),
            agent_interval_minutes=float(env("FLOP_AGENT_INTERVAL_MINUTES", "10")),
            qty_min=Decimal(env("FLOP_QTY_MIN", "0.1")),
            qty_max=Decimal(env("FLOP_QTY_MAX", "1.0")),
            max_position=Decimal(env("FLOP_MAX_POSITION", "5")),
            offer_edge=Decimal(env("FLOP_OFFER_EDGE", "0.01")),
            offer_sweeps=int(env("FLOP_OFFER_SWEEPS", "2")),
            take_slip=Decimal(env("FLOP_TAKE_SLIP", "0.002")),
            max_take_qty=Decimal(env("FLOP_MAX_TAKE_QTY", "3")),
            takes_per_minute=int(env("FLOP_TAKES_PER_MINUTE", "20")),
        )
