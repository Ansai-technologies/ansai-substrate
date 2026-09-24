"""Layer 3 — production traffic sampler (stub).

Samples N records from the gateway's request logs for continuous eval: the
sampled traffic is replayed through evals/judge.py on a schedule (cron), so
regressions in live agent behaviour get caught, not just pre-ship scenarios.

STUB: the sampling logic against LiteLLM's log DB is not wired yet — this
prints what it WOULD do. Wiring = read from the SQLite log DB
(gateway/litellm-logs.db, table per LiteLLM's schema — confirm table names
against the LiteLLM version in use) or the Postgres DB after the upgrade.

Usage: python evals/sample_prod.py --n 50
"""

import argparse


def main() -> None:
    p = argparse.ArgumentParser(description="Sample production traffic for eval (stub)")
    p.add_argument("--n", type=int, default=50, help="records to sample")
    args = p.parse_args()
    print(f"[stub] would sample {args.n} recent gateway requests for judge replay")
    print("[stub] wire to litellm log DB (see module docstring) to go live")


if __name__ == "__main__":
    main()
