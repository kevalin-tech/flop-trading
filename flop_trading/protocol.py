"""close-1 message shapes, as specified in technocore-close-call-challenge/close-call-game.md.

Terms are the JSON object with exactly the keys below, serialised with sorted keys and no spaces. The maker signs
`close-1|terms|<terms>`; the taker signs `close-1|accept|<terms>|<taker did>`.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from .keys import Key, verify

SEASON = "close-1"
TERM_KEYS = frozenset({"id", "maker", "px", "qty", "side", "taker", "until"})
DID = re.compile(r"did:key:z6Mk[1-9A-HJ-NP-Za-km-z]{44}")
TRADE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
TWO_PLACES = re.compile(r"[0-9]{1,7}(\.[0-9]{1,2})?")
CENT = Decimal("0.01")
MIN_QTY = Decimal("0.1")


def compact(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def amount(text) -> Decimal | None:
    if not isinstance(text, str) or not TWO_PLACES.fullmatch(text):
        return None
    value = Decimal(text)
    return value if value > 0 else None


def cents(value: Decimal, up: bool = False) -> str:
    return str(value.quantize(CENT, rounding=ROUND_CEILING if up else ROUND_FLOOR))


def new_id() -> str:
    return "kv" + secrets.token_hex(7)


def valid_terms(terms) -> bool:
    """The fold's shape check, plus well-formed DIDs."""
    if not isinstance(terms, dict) or set(terms) != TERM_KEYS:
        return False
    qty, px = amount(terms["qty"]), amount(terms["px"])
    return (isinstance(terms["id"], str) and bool(TRADE_ID.fullmatch(terms["id"]))
            and terms["side"] in ("buy", "sell") and qty is not None and qty >= MIN_QTY and px is not None
            and type(terms["until"]) is int
            and isinstance(terms["maker"], str) and bool(DID.fullmatch(terms["maker"]))
            and (terms["taker"] == "any" or (isinstance(terms["taker"], str) and bool(DID.fullmatch(terms["taker"])))))


def make_terms(maker: str, side: str, qty: Decimal, px: str, until: int, taker: str = "any", tid: str | None = None) -> dict:
    terms = {"id": tid or new_id(), "maker": maker, "px": px, "qty": cents(qty), "side": side, "taker": taker,
             "until": until}
    assert valid_terms(terms), terms
    return terms


def maker_sig(key: Key, terms: dict) -> str:
    return key.sign(f"{SEASON}|terms|{compact(terms)}")


def taker_sig(key: Key, terms: dict) -> str:
    return key.sign(f"{SEASON}|accept|{compact(terms)}|{key.did}")


def maker_sig_ok(terms: dict, sig: str) -> bool:
    return verify(terms["maker"], sig, f"{SEASON}|terms|{compact(terms)}")


def taker_sig_ok(terms: dict, taker: str, sig: str) -> bool:
    return verify(taker, sig, f"{SEASON}|accept|{compact(terms)}|{taker}")


def owner_text(did: str) -> str:
    return compact({"key": did, "season": SEASON, "t": "owner"})


def offer_text(terms: dict, sig: str) -> str:
    return compact({"how": "countersign close-1|accept|<terms>|<your did:key>, then post the trade",
                    "maker_sig": sig, "season": SEASON, "t": "offer", "terms": terms})


def trade_text(terms: dict, taker: str, m_sig: str, t_sig: str) -> str:
    return compact({"maker_sig": m_sig, "season": SEASON, "t": "trade", "taker": taker, "taker_sig": t_sig,
                    "terms": terms})


@dataclass
class Seen:
    """A close-1 message read from a room: an open offer someone could accept, or a countersigned trade."""
    kind: str               # "offer" or "trade"
    terms: dict
    maker_sig: str
    taker: str | None = None
    taker_sig: str | None = None
    poster: str | None = None


def parse(text: str, poster: str | None = None) -> Seen | None:
    """An offer is {"t":"offer",…} or a trade still missing taker_sig; a trade carries both signatures."""
    if not isinstance(text, str) or '"close-1"' not in text:
        return None
    try:
        msg = json.loads(text)
    except ValueError:
        return None
    if not isinstance(msg, dict) or msg.get("season") != SEASON or msg.get("t") not in ("offer", "trade"):
        return None
    terms, m_sig = msg.get("terms"), msg.get("maker_sig")
    if not valid_terms(terms) or not isinstance(m_sig, str):
        return None
    if msg["t"] == "trade" and isinstance(msg.get("taker_sig"), str) and isinstance(msg.get("taker"), str):
        return Seen("trade", terms, m_sig, msg["taker"], msg["taker_sig"], poster)
    return Seen("offer", terms, m_sig, poster=poster)
