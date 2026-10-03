import json
import unittest
from decimal import Decimal
from pathlib import Path

from flop_trading import protocol as p
from flop_trading.keys import Key, b58decode, b58encode, verify

SAMPLE = json.loads((Path(__file__).parent / "close1_sample.json").read_text())


class Signing(unittest.TestCase):
    def test_base58_roundtrip(self):
        for raw in (b"\x00\x00\xed\x01abc", bytes(range(34))):
            self.assertEqual(b58decode(b58encode(raw)), raw)

    def test_sign_verify(self):
        key = Key.generate()
        sig = key.sign("close1|1|hello")
        self.assertEqual(len(sig), 86)
        self.assertTrue(verify(key.did, sig, "close1|1|hello"))
        self.assertFalse(verify(key.did, sig, "close1|2|hello"))

    def test_our_terms_roundtrip(self):
        maker, taker = Key.generate(), Key.generate()
        terms = p.make_terms(maker.did, "buy", Decimal("0.5"), "231.40", 1800)
        self.assertEqual(terms["qty"], "0.50")
        m_sig, t_sig = p.maker_sig(maker, terms), p.taker_sig(taker, terms)
        seen = p.parse(p.trade_text(terms, taker.did, m_sig, t_sig), taker.did)
        self.assertEqual(seen.kind, "trade")
        self.assertTrue(p.maker_sig_ok(seen.terms, seen.maker_sig))
        self.assertTrue(p.taker_sig_ok(seen.terms, seen.taker, seen.taker_sig))
        offer = p.parse(p.offer_text(terms, m_sig))
        self.assertEqual(offer.kind, "offer")
        self.assertTrue(p.maker_sig_ok(offer.terms, offer.maker_sig))


class LiveSamples(unittest.TestCase):
    """Messages other agents posted in close1: our canonical terms must reproduce what they signed."""

    def test_samples_verify(self):
        kinds = set()
        for m in SAMPLE:
            seen = p.parse(m["text"], m["from"])
            kinds.add(seen.kind)
            self.assertTrue(p.maker_sig_ok(seen.terms, seen.maker_sig), m["text"][:80])
            if seen.kind == "trade":
                self.assertTrue(p.taker_sig_ok(seen.terms, seen.taker, seen.taker_sig))
        self.assertEqual(kinds, {"offer", "trade"})

    def test_rejects_bad_shapes(self):
        self.assertIsNone(p.parse('{"t":"owner","season":"close-1","key":"x"}'))
        self.assertIsNone(p.parse("not json close-1"))
        terms = json.loads(SAMPLE[0]["text"])["terms"]
        self.assertFalse(p.valid_terms({**terms, "qty": "0.05"}))
        self.assertFalse(p.valid_terms({**terms, "extra": 1}))


if __name__ == "__main__":
    unittest.main()
