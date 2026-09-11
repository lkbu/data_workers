"""
Script to backfill historical dividend data from StockWatch.pl into PostgreSQL.
Default: last 10 years up to the current calendar year.
"""

import argparse
import logging
import time
from datetime import date
from typing import Any

from sqlalchemy.engine import Engine

from core.data_hub.connection_manager import connection_manager
from core.util.telegram import send_telegram_notification
from core.workers.dividends import sync_dividends

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def format_backfill_telegram_message(
    start_year: int, end_year: int, summary: dict[str, Any]
) -> str:
    """
    Constructs a consolidated Telegram notification message for the backfill job.

    :param start_year: Starting calendar year of backfill.
    :param end_year: Ending calendar year of backfill.
    :param summary: Summary statistics dictionary.
    :return: Formatted HTML message string.
    """
    header = f"<b>[StockWatch Dividends - Backfill {start_year}-{end_year}]</b>"
    total_ins = summary.get("total_inserted", 0)
    total_upd = summary.get("total_updated", 0)
    total_del = summary.get("total_deleted", 0)
    total_unc = summary.get("total_unchanged", 0)
    total_processed = total_ins + total_upd + total_del + total_unc

    lines = [
        f"🎉 {header}",
        "Historical dividends backfill completed successfully!",
        "",
        f"📊 <b>Summary across {end_year - start_year + 1} years:</b>",
        f"• Total processed: <b>{total_processed}</b>",
        f"• Newly inserted: <b>+{total_ins}</b>",
        f"• Updated: <b>~{total_upd}</b>",
        f"• Deleted: <b>-{total_del}</b>",
        f"• Unchanged: <b>{total_unc}</b>",
        "",
        "<b>Breakdown by year:</b>",
    ]

    for yr, res in summary.get("by_year", {}).items():
        ins = res.get("inserted_count", 0)
        upd = res.get("updated_count", 0)
        unc = res.get("unchanged_count", 0)
        lines.append(f"• <b>{yr}</b>: +{ins} inserted, ~{upd} updated, {unc} unchanged")

    return "\n".join(lines).strip()


def backfill_dividends(
    start_year: int,
    end_year: int,
    db_engine: Engine | None = None,
    delay: float = 0.5,
    send_notification: bool = True,
) -> dict[str, Any]:
    """
    Iterates through a range of years, running sync_dividends for each year.

    :param start_year: Start year (inclusive).
    :param end_year: End year (inclusive).
    :param db_engine: Optional SQLAlchemy engine. Defaults to connection_manager.postgres_engine.
    :param delay: Pause in seconds between requests to be polite to the website.
    :param send_notification: Whether to send a consolidated Telegram message at the end.
    :return: Summary dictionary with per-year and aggregate results.
    """
    if db_engine is None:
        db_engine = connection_manager.postgres_engine

    if start_year > end_year:
        raise ValueError(
            f"start_year ({start_year}) cannot be greater than end_year ({end_year})."
        )

    logger.info(
        f"Starting dividends backfill from {start_year} to {end_year} ({end_year - start_year + 1} years)..."
    )

    summary: dict[str, Any] = {
        "start_year": start_year,
        "end_year": end_year,
        "total_inserted": 0,
        "total_updated": 0,
        "total_deleted": 0,
        "total_unchanged": 0,
        "by_year": {},
    }

    for yr in range(start_year, end_year + 1):
        logger.info(f"--- Processing year {yr} ---")
        res = sync_dividends(year=yr, db_engine=db_engine, send_notification=False)

        summary["by_year"][yr] = res
        summary["total_inserted"] += res.get("inserted_count", 0)
        summary["total_updated"] += res.get("updated_count", 0)
        summary["total_deleted"] += res.get("deleted_count", 0)
        summary["total_unchanged"] += res.get("unchanged_count", 0)

        logger.info(
            f"[Year {yr}] +{res.get('inserted_count', 0)} inserted, "
            f"~{res.get('updated_count', 0)} updated, "
            f"-{res.get('deleted_count', 0)} deleted, "
            f"{res.get('unchanged_count', 0)} unchanged."
        )

        if yr < end_year and delay > 0:
            time.sleep(delay)

    logger.info(
        f"Backfill finished: {summary['total_inserted']} inserted, "
        f"{summary['total_updated']} updated, "
        f"{summary['total_deleted']} deleted, "
        f"{summary['total_unchanged']} unchanged."
    )

    if send_notification:
        msg = format_backfill_telegram_message(
            start_year=start_year, end_year=end_year, summary=summary
        )
        sent = send_telegram_notification(msg)
        summary["telegram_sent"] = sent

    return summary


def run_standalone_backfill() -> None:
    """
    CLI runner for historical dividend backfilling.
    """
    current_year = date.today().year
    default_start_year = current_year - 9  # 10 years total: e.g. 2017 to 2026

    parser = argparse.ArgumentParser(
        description="Backfill historical dividend data from StockWatch.pl."
    )
    parser.add_argument(
        "--years",
        type=int,
        default=10,
        help="Number of years to backfill ending in current year (default: 10).",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        help=f"Explicit start year (default: current_year - years + 1 = {default_start_year}).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=current_year,
        help=f"Explicit end year (default: {current_year}).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay in seconds between years to avoid overwhelming the site (default: 0.5).",
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Disable sending the consolidated Telegram notification.",
    )

    args = parser.parse_args()

    end_year = args.end_year
    start_year = (
        args.start_year if args.start_year is not None else (end_year - args.years + 1)
    )

    print(f"Executing backfill for years {start_year} to {end_year}...")
    summary = backfill_dividends(
        start_year=start_year,
        end_year=end_year,
        delay=args.delay,
        send_notification=not args.no_telegram,
    )
    print(
        f"\nBackfill Complete: {summary['total_inserted']} inserted, "
        f"{summary['total_updated']} updated, "
        f"{summary['total_deleted']} deleted, "
        f"{summary['total_unchanged']} unchanged."
    )


if __name__ == "__main__":
    run_standalone_backfill()
