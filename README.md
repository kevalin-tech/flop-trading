# flop-trading

Runs our agent fleet in the Close Call contest (`close-1`) on technocore.chat, from registration until trading
locks at 09:00 UTC on Sunday 4 October 2026. The aim is to take part and trade with other agents, not to win.
`close-call/STRATEGY.md` explains why winning isn't realistic.

## What the agents do

- **Register:** each agent posts its signed `owner` message in `close1`. If no flow post shows its mint after
  an hour, it posts once more.
- **Make offers:** about every 10 minutes, each agent posts a small open offer (0.1–1 contract,
  `taker: "any"`) priced 1% better than Hyperliquid's `xyz:NVDA` mid for whoever takes it. The offer is
  valid for about 15 minutes. Each agent drifts towards its own target position (some lean long, some
  short) and keeps within ±5 contracts.
- **Take offers:** a reader thread follows `close1`, which runs at about 60 messages a second. When another
  agent's offer is within 0.2% of the market, signed correctly, valid for the next sweep, and up to 3
  contracts, an agent with room accepts it and posts the countersigned trade.
- **Avoid trading with ourselves:** our agents never take each other's offers.
- **Stop:** when the referee posts the lock sweep (2556), the app writes `state/DONE` and exits.

Cost per filled offer is about 2% of its value (1% fee plus the 1% price edge), roughly 1–5 POLF per
trade. Scores don't matter here, but the settings are in `.env` if you want to change them.

## Install on Opalstack

SSH in as the app's shell user, then:

```sh
mkdir -p ~/apps && cd ~/apps
git clone <this repo's URL> flop-trading
cd flop-trading
python3 -m venv env
env/bin/pip install -r requirements.txt
cp .env.example .env
```

Copy the roster and keys from your machine. They are gitignored and never go through git:

```sh
# from your machine, in the flop folder
scp flop-technocore/names/roster.json            <user>@<server>:~/apps/flop-trading/roster.json
scp flop-technocore/sec/agents/*.pem             <user>@<server>:~/apps/flop-trading/keys/
ssh <user>@<server> 'chmod 700 ~/apps/flop-trading/keys && chmod 600 ~/apps/flop-trading/keys/*.pem'
```

Check, then rehearse without posting:

```sh
env/bin/python -m flop_trading check            # "500 of 500 roster agents have a matching key"
env/bin/python -m flop_trading run --dry-run    # reads live, signs, posts nothing; Ctrl-C after a few minutes
```

Go live: start the fleet and keep it running with cron (`crontab -e`):

```
*/10 * * * * $HOME/apps/flop-trading/start > /dev/null 2>&1
```

`start` does nothing while the fleet is running or after `state/DONE` exists, so cron only restarts it if it
crashed or the server rebooted. Run `./start` once by hand to begin right away. To begin small, set
`FLOP_MAX_AGENTS=20` in `.env`, then raise it to `0` (the whole roster) and run `./stop && ./start`.

## Watching it

```sh
env/bin/python -m flop_trading status     # registered, offers posted / taken by others, offers we accepted, counterparties
tail -f state/flop-trading.log            # a summary line every 5 minutes
```

There are three limits on what we can confirm:
- **Settlement:** only the referee's `d-close1-flow` posts confirm a trade, and they cut their lists to fit
  4,096 characters, so most of our ids never appear there. Counts of fills and positions are optimistic,
  based on trades we saw posted.
- **Fills:** an offer taken in a room other than `close1` goes unseen.
- **The archive:** the full record at https://challenges.technocore.chat/close-1/ runs about two days
  behind.

## Limits it respects

- **technocore.chat:** 300 writes and 600 reads per minute per IP. The app uses 100 and 300 by default,
  sharing the IP with anything else on the server, and backs off on a 429.
- **Nonces:** epoch milliseconds, strictly increasing per key across restarts (kept in `state/fleet.sqlite`).
- **Prices:** every price stays inside the referee's next-sweep limits (±5% of the last reference), with
  0.5% to spare.

## Develop

```sh
python3 -m unittest discover -s tests -v
python3 -m flop_trading run --demo 20     # dry run with 20 throwaway keys under state/demo/
```

`tests/close1_sample.json` holds real offers and trades from `close1`. The tests check that our canonical
terms reproduce the exact bytes other agents signed.
