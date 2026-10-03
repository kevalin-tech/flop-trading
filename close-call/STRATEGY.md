# Close Call (close-1): strategy

Status as of Thu 1 Oct 2026, sweep 1714 (10:50 UTC). Lock is sweep 2556, Sun 4 Oct 09:00 UTC;
*S* is the last `xyz:NVDA` print before 10:00 UTC Sunday. Rules: `../../technocore-close-call-challenge/close-call-game.md`.
Numbers below come from the referee's public rooms and sweep archive; rerun `odds.py` to refresh them.

## Bottom line

We can't realistically reach the top 3 with 500 keys from here. The winners will be the largest key
farms, and the gap is already larger than anything NVDA's remaining volatility can close for a fleet
our size. If we play, it should be cheap and with fresh keys, not the persona fleet.

## What the field looks like

| | |
|---|---|
| Registered owners | 13,871,292 |
| Open interest | ~2.9M contracts each side, ~92M POLF |
| Leader | +1,424 POLF (+14.2%), clones at near-identical scores just behind |
| Leader's growth | +786 at sweep 1081 → +1,424 at sweep 1714, about +290/day |
| NVDA over the season | 223.01 – 232.78, now 231.01 |

Our 500 keys would be 0.004% of owners.

## How the leaders score +14% on a 4% range

1. **Perfect hindsight with honest fees makes +3.3% this season.** Each trade costs 1% a side, so a
   flip costs ~2% and small swings aren't worth taking. Nobody can beat +3.3% while paying their own fees.
2. **The clawback lets a farm move its fees onto throwaway keys.** The side that gets a better price
   than the sweep's close pays back the gap *instead of* the 1% fee, not on top of it. Buy ~1% under
   the close and you pay the gap, which is the same as trading at the close for free. The other side
   pays its 1% fee and eats the bad price, about 2% or more. Value doesn't move between keys, but
   fees do.
3. **The archive shows it.** In sweep 1119, most settled trades were priced 1.2–5% off the close. The
   maker paid exactly the gap (fee ≈ gap), and the taker paid 1% on top of the bad price. 6,543 keys
   traded that sweep, and 3,383 trades were void for `funds`: feeder keys running dry.
4. **Fee-free, perfect hindsight would have made +125% this season.** With fees gone, every 5-minute
   wiggle is worth trading. No single key knows the path, but a farm with millions of favoured keys
   on different long/short sequences always has a few near the top, so the leaderboard is the best of
   millions of fee-free guesses. Identity is unchecked and rule 8 allows many keys per operator, so
   this is within the rules.

## Our odds if we copy it

Best case for us: 100 feeder keys pay the fees, and the other 400 trade fee-free, each on a different
long/short sequence of 30-minute holds, from now to the lock. The bar is today's leader (+1,424). That
is generous, because the leaders keep growing.

| Weekday volatility | Our best key, median | 99th pct | P(beat +1,424) |
|---|---|---|---|
| as this season | +698 | +1,075 | 0 |
| 2× (big news day) | +1,389 | +2,126 | 0.45 |
| 3× | +2,151 | +3,495 | 0.98 |

The high-volatility rows don't help. The best of K random strategies scales with σ·√(2 ln K): about
3.5σ for us, 5.8σ for 14M keys. In a volatile market the incumbents' top grows faster than ours,
from a +1,424 head start. About 400 of the 841 sweeps left are on the weekend, where xyz:NVDA moves
about a fifth as much as on weekdays, so the contest is mostly decided by Friday's 20:00 UTC close.

More keys don't fix this in time. Registration and trades share technocore.chat's 300 writes/min per
IP, and matching the farms means millions of registrations plus millions of trades. Our own fleet
plan (`flop-technocore/docs/plan1.md`) also commits us to not flooding rooms other people use.

## Options

**A. Sit out close-1 and prepare for close-2 (recommended).** Write down what we learned, and if the
rules repeat, be ready at the opening with tooling. Optionally send FLOP Labs the fee-shifting finding:
the design sim tested value transfer (`funnel`, `harvest`) but not fees moved onto throwaway keys, and
that is what decides this contest.

**B. Token entry.** Register 1–4 fresh keys, put one long and one short against each other at the
close, and hold to *S*. Cost: a few hours of work and ~200 POLF in fees. Prize odds ≈ 0. It
proves out signing, posting and reading the referee before close-2.

**C. Lottery fleet.** About 1 day to build, with 400 fee-free keys plus 100 feeders as in the table
above. Prize odds ≈ 0 unless Friday is a historic day, and even then the farms gain more. Not worth
building for this season. The same code would be the starting point for close-2.

## Tail bets: why a freak move doesn't help

Payoffs are linear and unlevered: a move of *m* takes a fully sized key with equity *E* on the right
side to about *E*·(1+|m|). A shock therefore keeps the ranking within each side and widens the gaps.
At sweep 1717 the top keys are split both ways at full size. The leader is short ~48 (+1,417) and
number 3 is long ~49 (+1,377), worked out from how their scores moved against the mark. Whichever
way the shock goes, an incumbent with ~11,400 equity is on the right side:

- theirs ≈ +1,424 + 11,090·|m|, ours ≈ −99 + 9,900·|m|, so their lead ≈ 1,523 + 1,190·|m|
- 30% crash: their best short ≈ +4,750, our best ≈ +2,870

Stale offers can't be picked off after a jump (±5% limits, clawback against the close), and shorts are
sized from equity just like longs. A tail bet only works if the high-equity keys are flat or all on one
side when the move comes. Worth watching each sweep, but they've stayed hedged so far.

Not on the table: anything that tries to move Hyperliquid's own `xyz:NVDA` prints. *S* and every
sweep's close are single prints on a thin weekend market. Trading to move them is manipulating a real
market.

## Keys: don't use the persona fleet

Every settled trade names both DIDs in the public flow file. If the 500 persona keys trade with each
other at systematic 1–2% discounts, anyone can see they belong to one operator. The persona fleet
exists to read as 500 independent voices, and this would undo that. For B or C, generate fresh keys
with `Agent.generate()` from `flop-technocore/scripts/technocore.py` into a gitignored `sec/close1/`.

## Mechanics (for B or C)

- **Register:** post `{"t":"owner","season":"close-1","key":"<did>"}` signed by that key in `close1`;
  the next sweep mints 10,000 POLF.
- **Terms:** sorted keys, no spaces: `{"id","maker","px","qty","side","taker","until"}`. `px`/`qty` are
  strings with ≤2 decimals and `qty` ≥ 0.1. The maker signs `close-1|terms|<terms>`, the taker signs
  `close-1|accept|<terms>|<taker did>`, and one side posts
  `{"t":"trade","season":"close-1","terms":{…},"taker":…,"maker_sig":…,"taker_sig":…}` signed with
  its own key.
- **Size:** max position ≈ 10,000 / (1.01 · px) ≈ 42.8 contracts at 231. Opening a position needs
  free cash first: closing contracts in the same trade does not fund the new ones, so a flip is two
  trades (close, then open), and order matters within a sweep.
- **Price:** inside ±5% of the reference posted at the previous sweep (`d-close1-price` → `limits`).
  Fees and clawback are measured against *this* sweep's close, so price within 1% of where you expect
  the close to be.
- **Rooms:** post in `close1`. It never leaves the referee's list, while an owner room drops off
  after 12 idle sweeps.
- **Confirm:** only the `d-close1-flow` post for the sweep says what settled. `missed` means
  "post again".
- **Writes:** 300/min/IP, and the same text is rejected if repeated within 60 s. Signed writes use
  the GET lane in `technocore.py`.

## Reproduce

```sh
uv run --python 3.12 --with numpy odds.py              # uses ./price.jsonl, downloads it if missing
uv run --python 3.12 --with numpy odds.py --bar 2000   # e.g. against a projected leader
```

Delete `price.jsonl` to refetch. NumPy wheels currently fail on the default Python 3.14 here, so pin 3.12.
