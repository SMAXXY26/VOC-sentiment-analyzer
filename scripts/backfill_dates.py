"""Backfill stored_at dates on already-stored feedback so the dashboard's
day/week/month volume chart and time-window queries (drift/retrieval) span a range.

Unlike `load_cx_data.py --spread-days` (which dates items during a fresh GPU re-run),
this re-dates points ALREADY in Qdrant via set_payload — no LLM, no GPU, seconds.

Usage:
    python scripts/backfill_dates.py --days 365              # spread ALL points over last year
    python scripts/backfill_dates.py --days 365 --only-missing  # only points lacking stored_at
    python scripts/backfill_dates.py --days 90 --source hf_seed # restrict to one source
    python scripts/backfill_dates.py --days 365 --dry-run        # preview, write nothing

Requires Qdrant reachable (QDRANT_URL).
"""

import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.progress import track  # noqa: E402

from vectordb.client import ANALYSES_COLLECTION, get_client  # noqa: E402

load_dotenv()
console = Console()


def main():
    p = argparse.ArgumentParser(description="Backfill stored_at dates on stored feedback points.")
    p.add_argument("--days", type=int, default=365, help="spread stored_at uniformly over the last N days")
    p.add_argument("--source", default=None, help="only re-date points with this payload 'source' (default: all)")
    p.add_argument("--only-missing", action="store_true", help="only set points that have no stored_at yet")
    p.add_argument("--dry-run", action="store_true", help="report what would change without writing")
    args = p.parse_args()

    if args.days <= 0:
        raise SystemExit("--days must be > 0")

    client = get_client()
    span = args.days * 86400
    now = time.time()

    # Optional source filter.
    scroll_filter = None
    if args.source:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        scroll_filter = Filter(must=[FieldCondition(key="source", match=MatchValue(value=args.source))])

    # Page through every point.
    points = []
    offset = None
    while True:
        batch, offset = client.scroll(
            collection_name=ANALYSES_COLLECTION,
            scroll_filter=scroll_filter,
            limit=250,
            offset=offset,
            with_payload=True,
        )
        points.extend(batch)
        if offset is None:
            break

    if args.only_missing:
        points = [pt for pt in points if pt.payload.get("stored_at") is None]

    if not points:
        console.print("[yellow]No matching points to re-date.[/yellow]")
        return

    console.print(
        f"[bold cyan]{'(dry-run) ' if args.dry_run else ''}Re-dating {len(points)} points "
        f"across the last {args.days} days...[/bold cyan]"
    )

    updated = 0
    for pt in track(points, description="Backfilling dates..."):
        stored_at = now - random.uniform(0, span)
        if args.dry_run:
            updated += 1
            continue
        try:
            client.set_payload(
                collection_name=ANALYSES_COLLECTION,
                payload={"stored_at": stored_at},
                points=[pt.id],
            )
            updated += 1
        except Exception as exc:
            console.print(f"[yellow]skip {pt.id}: {str(exc)[:80]}[/yellow]")

    verb = "would update" if args.dry_run else "updated"
    console.print(f"[bold green]Done. {verb} {updated}/{len(points)} points.[/bold green]")
    console.print("Refresh the dashboard — the volume chart should now span the backfilled range.")


if __name__ == "__main__":
    main()
