"""Ed25519 did:key identities: load, sign, verify. Same key format as flop-technocore/scripts/technocore.py."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58)}
_ED25519_PREFIX = b"\xed\x01"


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(data) - len(data.lstrip(b"\x00"))) + out


def b58decode(text: str) -> bytes:
    n = 0
    for c in text:
        n = n * 58 + _B58_INDEX[c]
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\x00" * (len(text) - len(text.lstrip("1"))) + body


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def did_for(public: bytes) -> str:
    return "did:key:z" + b58encode(_ED25519_PREFIX + public)


@lru_cache(maxsize=65536)
def public_key(did: str) -> Ed25519PublicKey | None:
    if not did.startswith("did:key:z6Mk"):
        return None
    try:
        raw = b58decode(did[len("did:key:z"):])
    except KeyError:
        return None
    if len(raw) != 34 or raw[:2] != _ED25519_PREFIX:
        return None
    return Ed25519PublicKey.from_public_bytes(raw[2:])


def verify(did: str, sig: str, payload: str) -> bool:
    key = public_key(did)
    if key is None or not isinstance(sig, str) or len(sig) != 86:
        return False
    try:
        key.verify(unb64u(sig), payload.encode())
        return True
    except (InvalidSignature, ValueError):
        return False


class Key:
    """One agent's signing key. The private key never leaves this object."""

    def __init__(self, private: Ed25519PrivateKey):
        self._private = private
        raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.did = did_for(raw)

    @classmethod
    def load(cls, path: Path) -> "Key":
        private = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        if not isinstance(private, Ed25519PrivateKey):
            raise ValueError(f"{path}: not an Ed25519 key")
        return cls(private)

    @classmethod
    def generate(cls, path: Path | None = None) -> "Key":
        private = Ed25519PrivateKey.generate()
        if path is not None:
            path = Path(path)
            if path.exists():
                raise FileExistsError(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
            path.chmod(0o600)
        return cls(private)

    def sign(self, payload: str) -> str:
        """Unpadded base64url Ed25519 signature (86 chars) over the UTF-8 payload."""
        return b64u(self._private.sign(payload.encode()))

    def __repr__(self) -> str:
        return f"Key({self.did})"
