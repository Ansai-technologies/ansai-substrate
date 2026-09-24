#!/usr/bin/env python3
"""Human side of the HITL queue.

Usage:
  python policy/approve.py list
  python policy/approve.py approve <id> [--reason "..."]
  python policy/approve.py deny <id> [--reason "..."]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from approvals import approve, deny, list_pending


def main() -> None:
    p = argparse.ArgumentParser(description="Decide pending agent approvals")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show pending approvals")

    for name in ("approve", "deny"):
        sp = sub.add_parser(name, help=f"{name} a pending approval")
        sp.add_argument("id", help="approval id from list")
        sp.add_argument("--reason", default="", help="why (recorded)")

    args = p.parse_args()

    if args.cmd == "list":
        pending = list_pending()
        if not pending:
            print("no pending approvals")
            return
        for r in pending:
            print(f"- {r['id']} [{r['requested_at']}] {r['action'].get('kind')}: "
                  f"{r['action'].get('summary')}")
            print(f"  payload: {json.dumps(r['action'].get('payload', {}), ensure_ascii=False)[:200]}")
    elif args.cmd == "approve":
        print("approved" if approve(args.id, args.reason) else "id not found")
    elif args.cmd == "deny":
        print("denied" if deny(args.id, args.reason) else "id not found")


if __name__ == "__main__":
    main()
