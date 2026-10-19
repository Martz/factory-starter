"""Command line: python -m lunchbox ORDER.csv

CSV columns: person,item,price[,tags]   (tags separated by ';', e.g. "vegan;gf")
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .orders import Order


def load(path: Path) -> Order:
    order = Order()
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tags = tuple((row.get("tags") or "").split(";"))
            order.add(row["person"], row["item"], row["price"], tags)
    return order


def render(order: Order) -> str:
    lines = [f"{'person':<12}{'owes':>8}"]
    for person, amount in order.per_person().items():
        lines.append(f"{person:<12}{amount:>8}")
    lines.append(f"{'TOTAL':<12}{order.total():>8}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lunchbox", description="Split a group lunch order.")
    ap.add_argument("order", type=Path, help="CSV file: person,item,price[,tags]")
    args = ap.parse_args(argv)
    print(render(load(args.order)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
