"""
Worker for scraping, parsing, reconciling, and storing Polish stock dividend data
from StockWatch.pl (https://www.stockwatch.pl/dywidendy/).
"""

import argparse
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import requests
from bs4 import BeautifulSoup
from prefect import flow, task
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.data_hub.connection_manager import connection_manager
from core.util.telegram import send_telegram_notification

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STOCKWATCH_ASYNC_URL = (
    "https://www.stockwatch.pl/async/dividendsview.aspx"
    "?year={year}&s=default.aspx&pp=false&IndexTicker=Wszystkie"
)
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def fetch_dividends_html(year: int, timeout: int = 15) -> str:
    """
    Fetches raw HTML response containing the dividends table for a given year.

    :param year: The dividend year to fetch.
    :param timeout: Request timeout in seconds.
    :return: Decoded HTML string.
    """
    url = STOCKWATCH_ASYNC_URL.format(year=year)
    logger.info(f"Fetching dividends data for year {year} from {url}...")
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def extract_js_variables(html: str) -> dict[str, str]:
    """
    Extracts tooltip text variables (e.g. var bbdvm... = "...";) embedded in page scripts.

    :param html: HTML content of the page.
    :return: Dictionary mapping variable names to their string values.
    """
    js_vars: dict[str, str] = {}
    pattern = re.compile(r'var\s+(bbdv[tm]\d+)\s*=\s*"([^"]*)";')
    for match in pattern.finditer(html):
        js_vars[match.group(1)] = match.group(2).strip()
    return js_vars


def parse_date_string(date_str: str | None) -> date | None:
    """
    Parses a string formatted as YYYY-MM-DD into a date object.

    :param date_str: String date representation or None.
    :return: date object or None if empty/invalid.
    """
    if not date_str:
        return None
    cleaned = date_str.strip()
    if cleaned in ("", "-", "brak", "None"):
        return None
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError:
        logger.warning(f"Could not parse date string: '{date_str}'")
        return None


def parse_numeric_value(val_str: str | None) -> float | None:
    """
    Parses a localized number string (with comma decimal separator) to a float.

    :param val_str: Number string e.g. '0,17' or '900,00'.
    :return: Float value or None.
    """
    if not val_str:
        return None
    cleaned = val_str.strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    cleaned = re.sub(r"[^\d.-]", "", cleaned)
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        logger.warning(f"Could not parse numeric value: '{val_str}'")
        return None


def parse_yield_fraction(yield_str: str | None) -> float | None:
    """
    Parses a dividend yield string (e.g. '4,11%') and converts it to a decimal fraction (e.g. 0.0411).

    :param yield_str: Percentage string.
    :return: Float decimal fraction or None.
    """
    num = parse_numeric_value(yield_str)
    if num is None:
        return None
    return round(num / 100.0, 6)


def parse_currency_code(note: str, default: str = "PLN") -> str:
    """
    Determines dividend currency code based on note contents.

    :param note: Tooltip note or comment.
    :param default: Default currency if none mentioned.
    :return: Currency symbol/code (e.g. 'EUR', 'HUF', 'USD', 'PLN').
    """
    lower = note.lower()
    if "euro" in lower or "eur" in lower:
        return "EUR"
    if "huf" in lower:
        return "HUF"
    if "usd" in lower:
        return "USD"
    return default


def parse_dividends_table(html: str, year: int) -> list[dict[str, Any]]:
    """
    Parses the HTML table into structured dividend records.

    :param html: Raw HTML from StockWatch.
    :param year: The year under which records were listed.
    :return: List of parsed dividend dictionaries.
    """
    soup = BeautifulSoup(html, "html.parser")
    js_vars = extract_js_variables(html)

    table = soup.find("table", class_="cctabdt")
    if not table:
        logger.warning(f"No dividend table found in HTML for year {year}.")
        return []

    rows = table.find_all("tr")[1:]  # Skip header row
    parsed_records: list[dict[str, Any]] = []

    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 8:
            continue

        # Column 0: Spółka (Company & Ticker)
        company_elem = tds[0].find("a")
        company_name = (
            company_elem.get_text(strip=True)
            if company_elem
            else tds[0].get_text(strip=True)
        )
        ticker_slug = None
        if company_elem and company_elem.get("href"):
            match = re.search(r"/gpw/([^,]+)", company_elem["href"])
            if match:
                ticker_slug = match.group(1)

        # Column 1: Za okres (e.g. 'od 2025-01-01 do 2025-12-31')
        period_text = tds[1].get_text(separator=" ", strip=True).replace("\xa0", " ")
        period_match = re.search(
            r"od\s+(\d{4}-\d{2}-\d{2})\s+do\s+(\d{4}-\d{2}-\d{2})", period_text
        )
        period_from = parse_date_string(period_match.group(1)) if period_match else None
        period_to = parse_date_string(period_match.group(2)) if period_match else None

        # Column 2: Stan wypłaty (Status, payment date, tooltip note)
        status_td = tds[2]
        stcm_div = status_td.find("div", class_="stcm")
        payment_date = (
            parse_date_string(stcm_div.get_text(strip=True)) if stcm_div else None
        )

        bubbly_span = status_td.find("span", class_="bubbly")
        note = ""
        if bubbly_span:
            bbm = bubbly_span.get("data-bbm", "")
            note = js_vars.get(bbm, "")

        # Extract only the status text (e.g. 'proponowana', 'uchwalona', 'wypłacona')
        status_copy = BeautifulSoup(str(status_td), "html.parser")
        for tag in status_copy.find_all(["div", "span", "i"]):
            tag.decompose()
        status_text = status_copy.get_text(strip=True)

        # Column 3: Dyw. na akcje
        dps_val = parse_numeric_value(tds[3].get_text(strip=True))
        currency = parse_currency_code(note)

        # Column 4: Stopa (Yield fraction)
        yield_val = parse_yield_fraction(tds[4].get_text(strip=True))

        # Column 5: Ustalenie prawa
        record_date = parse_date_string(tds[5].get_text(strip=True))

        # Column 6: Notowanie bez dyw.
        ex_date = parse_date_string(tds[6].get_text(strip=True))

        # Column 7: Data WZA
        agm_date = parse_date_string(tds[7].get_text(strip=True))

        parsed_records.append(
            {
                "dividend_year": year,
                "company_name": company_name,
                "ticker_slug": ticker_slug,
                "period_from": period_from,
                "period_to": period_to,
                "status": status_text,
                "payment_date": payment_date,
                "record_date": record_date,
                "ex_date": ex_date,
                "agm_date": agm_date,
                "dps": dps_val,
                "currency": currency,
                "dividend_yield": yield_val,
                "note": note,
            }
        )

    logger.info(f"Successfully parsed {len(parsed_records)} rows for year {year}.")
    return parsed_records


def fetch_existing_dividends(db_engine: Engine, year: int) -> list[dict[str, Any]]:
    """
    Retrieves existing dividend rows for a given year from mdh.dividends.

    :param db_engine: SQLAlchemy Engine.
    :param year: The dividend year.
    :return: List of dictionaries matching existing rows.
    """
    query = text(
        """
        SELECT
            id,
            dividend_year,
            company_name,
            ticker_slug,
            period_from,
            period_to,
            status,
            payment_date,
            record_date,
            ex_date,
            agm_date,
            dps,
            currency,
            dividend_yield,
            note
        FROM mdh.dividends
        WHERE dividend_year = :year
        ORDER BY id ASC;
        """
    )
    with db_engine.connect() as conn:
        result = conn.execute(query, {"year": year})
        rows = [dict(row._mapping) for row in result]
    return rows


def _are_values_equal(val1: Any, val2: Any) -> bool:
    """
    Compares two values taking into account Decimals/floats and None/empty strings.
    """
    if val1 is None and val2 is None:
        return True
    if val1 is None or val2 is None:
        if val1 == "" or val2 == "":
            return True
        return False

    # Handle float / Decimal comparison
    if isinstance(val1, (float, Decimal)) and isinstance(val2, (float, Decimal)):
        return round(float(val1), 4) == round(float(val2), 4)

    # String comparison (strip whitespace)
    if isinstance(val1, str) and isinstance(val2, str):
        return val1.strip() == val2.strip()

    return val1 == val2


def _detect_row_diffs(
    existing: dict[str, Any], scraped: dict[str, Any]
) -> dict[str, tuple[Any, Any]]:
    """
    Compares relevant fields between existing and scraped records, returning field differences.
    """
    fields_to_compare = [
        "status",
        "payment_date",
        "record_date",
        "ex_date",
        "agm_date",
        "dps",
        "currency",
        "dividend_yield",
        "note",
        "period_from",
        "period_to",
        "ticker_slug",
    ]
    diffs = {}
    for f in fields_to_compare:
        old_v = existing.get(f)
        new_v = scraped.get(f)
        if not _are_values_equal(old_v, new_v):
            diffs[f] = (old_v, new_v)
    return diffs


def reconcile_dividends(
    existing_rows: list[dict[str, Any]], scraped_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """
    Compares scraped records against existing database records for a given year.
    Determines which entries to insert, update (with diffs), or delete.

    :param existing_rows: Existing records from mdh.dividends.
    :param scraped_rows: Newly parsed records from StockWatch.
    :return: Reconciliation summary dictionary.
    """
    # Group by company_name
    existing_by_company: dict[str, list[dict[str, Any]]] = {}
    for row in existing_rows:
        existing_by_company.setdefault(row["company_name"], []).append(row)

    scraped_by_company: dict[str, list[dict[str, Any]]] = {}
    for row in scraped_rows:
        scraped_by_company.setdefault(row["company_name"], []).append(row)

    all_companies = set(existing_by_company.keys()).union(scraped_by_company.keys())

    to_insert: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []
    to_delete: list[dict[str, Any]] = []
    unchanged_count = 0

    for company in all_companies:
        exist_list = existing_by_company.get(company, [])
        scrap_list = scraped_by_company.get(company, [])

        if not exist_list:
            # Entire company is new
            for s in scrap_list:
                to_insert.append(s)
            continue

        if not scrap_list:
            # Company removed from website
            for e in exist_list:
                to_delete.append(e)
            continue

        # If both have exactly 1 entry: match directly
        if len(exist_list) == 1 and len(scrap_list) == 1:
            e = exist_list[0]
            s = scrap_list[0]
            diffs = _detect_row_diffs(e, s)
            if diffs:
                to_update.append(
                    {
                        "id": e["id"],
                        "company_name": company,
                        "data": s,
                        "diffs": diffs,
                    }
                )
            else:
                unchanged_count += 1
            continue

        # Multiple entries for this company: pair them using heuristics
        # 1. Match by note (e.g. 'I rata', 'zaliczka na poczet dywidendy') if note is non-empty
        matched_exist_ids: set[int] = set()
        matched_scrap_indices: set[int] = set()

        for s_idx, s in enumerate(scrap_list):
            if s.get("note"):
                for e in exist_list:
                    if e["id"] not in matched_exist_ids and e.get("note") == s["note"]:
                        matched_exist_ids.add(e["id"])
                        matched_scrap_indices.add(s_idx)
                        diffs = _detect_row_diffs(e, s)
                        if diffs:
                            to_update.append(
                                {
                                    "id": e["id"],
                                    "company_name": company,
                                    "data": s,
                                    "diffs": diffs,
                                }
                            )
                        else:
                            unchanged_count += 1
                        break

        # 2. Match remaining by payment_date
        for s_idx, s in enumerate(scrap_list):
            if s_idx in matched_scrap_indices:
                continue
            if s.get("payment_date"):
                for e in exist_list:
                    if (
                        e["id"] not in matched_exist_ids
                        and e.get("payment_date") == s["payment_date"]
                    ):
                        matched_exist_ids.add(e["id"])
                        matched_scrap_indices.add(s_idx)
                        diffs = _detect_row_diffs(e, s)
                        if diffs:
                            to_update.append(
                                {
                                    "id": e["id"],
                                    "company_name": company,
                                    "data": s,
                                    "diffs": diffs,
                                }
                            )
                        else:
                            unchanged_count += 1
                        break

        # 3. Match remaining sequentially
        remaining_exist = [e for e in exist_list if e["id"] not in matched_exist_ids]
        remaining_scrap = [
            (idx, s)
            for idx, s in enumerate(scrap_list)
            if idx not in matched_scrap_indices
        ]

        pair_count = min(len(remaining_exist), len(remaining_scrap))
        for i in range(pair_count):
            e = remaining_exist[i]
            s_idx, s = remaining_scrap[i]
            matched_exist_ids.add(e["id"])
            matched_scrap_indices.add(s_idx)
            diffs = _detect_row_diffs(e, s)
            if diffs:
                to_update.append(
                    {
                        "id": e["id"],
                        "company_name": company,
                        "data": s,
                        "diffs": diffs,
                    }
                )
            else:
                unchanged_count += 1

        # Any remaining unmatched scraped -> INSERT
        for s_idx, s in enumerate(scrap_list):
            if s_idx not in matched_scrap_indices:
                to_insert.append(s)

        # Any remaining unmatched existing -> DELETE
        for e in exist_list:
            if e["id"] not in matched_exist_ids:
                to_delete.append(e)

    return {
        "to_insert": to_insert,
        "to_update": to_update,
        "to_delete": to_delete,
        "unchanged_count": unchanged_count,
        "total_scraped": len(scraped_rows),
        "total_existing": len(existing_rows),
    }


def execute_dividends_sync(
    db_engine: Engine, year: int, reconciliation: dict[str, Any]
) -> dict[str, Any]:
    """
    Applies reconciliation actions (insert, update, delete) to the database inside a transaction.

    :param db_engine: SQLAlchemy Engine.
    :param year: Dividend year.
    :param reconciliation: Output from reconcile_dividends.
    :return: Summary dictionary of executed actions.
    """
    to_insert = reconciliation["to_insert"]
    to_update = reconciliation["to_update"]
    to_delete = reconciliation["to_delete"]

    insert_sql = text(
        """
        INSERT INTO mdh.dividends (
            dividend_year,
            company_name,
            ticker_slug,
            period_from,
            period_to,
            status,
            payment_date,
            record_date,
            ex_date,
            agm_date,
            dps,
            currency,
            dividend_yield,
            note,
            created_at,
            updated_at
        ) VALUES (
            :dividend_year,
            :company_name,
            :ticker_slug,
            :period_from,
            :period_to,
            :status,
            :payment_date,
            :record_date,
            :ex_date,
            :agm_date,
            :dps,
            :currency,
            :dividend_yield,
            :note,
            NOW(),
            NOW()
        );
        """
    )

    update_sql = text(
        """
        UPDATE mdh.dividends
        SET
            company_name = :company_name,
            ticker_slug = :ticker_slug,
            period_from = :period_from,
            period_to = :period_to,
            status = :status,
            payment_date = :payment_date,
            record_date = :record_date,
            ex_date = :ex_date,
            agm_date = :agm_date,
            dps = :dps,
            currency = :currency,
            dividend_yield = :dividend_yield,
            note = :note,
            updated_at = NOW()
        WHERE id = :id;
        """
    )

    delete_sql = text("DELETE FROM mdh.dividends WHERE id = :id;")

    with db_engine.begin() as conn:
        for row in to_insert:
            conn.execute(insert_sql, row)

        for item in to_update:
            params = {**item["data"], "id": item["id"]}
            conn.execute(update_sql, params)

        for row in to_delete:
            conn.execute(delete_sql, {"id": row["id"]})

    logger.info(
        f"Sync executed for year {year}: "
        f"{len(to_insert)} inserted, {len(to_update)} updated, {len(to_delete)} deleted."
    )

    return {
        "status": "success",
        "inserted_count": len(to_insert),
        "updated_count": len(to_update),
        "deleted_count": len(to_delete),
        "unchanged_count": reconciliation["unchanged_count"],
        "inserted_items": to_insert,
        "updated_items": to_update,
        "deleted_items": to_delete,
    }


def format_telegram_message(year: int, result: dict[str, Any]) -> str:
    """
    Constructs a detailed Telegram notification message detailing changes.

    :param year: The dividend year.
    :param result: Result dictionary from sync_dividends.
    :return: Formatted message string (HTML supported by Telegram).
    """
    header = f"<b>[StockWatch Dividends - {year}]</b>"

    if result.get("status") == "failed":
        err = result.get("error", "Unknown error")
        return f"🚨 {header}\nFlow encountered an error:\n<code>{err}</code>"

    ins_count = result.get("inserted_count", 0)
    upd_count = result.get("updated_count", 0)
    del_count = result.get("deleted_count", 0)
    unchanged_count = result.get("unchanged_count", 0)

    if ins_count == 0 and upd_count == 0 and del_count == 0:
        return (
            f"ℹ️ {header}\n"
            f"Database is already up to date. "
            f"All {unchanged_count} entries match."
        )

    lines = [
        f"🔔 {header}",
        f"Sync completed: <b>+{ins_count}</b> inserted, <b>~{upd_count}</b> updated, <b>-{del_count}</b> deleted.",
        "",
    ]

    # Inserted items section
    if ins_count > 0:
        lines.append(f"➕ <b>New entries ({ins_count}):</b>")
        for item in result.get("inserted_items", [])[:15]:
            dps_str = (
                f"{item['dps']} {item.get('currency', 'PLN')}"
                if item.get("dps") is not None
                else "N/A"
            )
            pay_str = (
                f", pay: {item['payment_date']}" if item.get("payment_date") else ""
            )
            note_str = f" [{item['note']}]" if item.get("note") else ""
            lines.append(
                f"• <b>{item['company_name']}</b>: {dps_str} ({item['status']}{pay_str}){note_str}"
            )
        if ins_count > 15:
            lines.append(f"  <i>...and {ins_count - 15} more</i>")
        lines.append("")

    # Updated items section
    if upd_count > 0:
        lines.append(f"✏️ <b>Updated entries ({upd_count}):</b>")
        for item in result.get("updated_items", [])[:15]:
            company = item["company_name"]
            diff_strs = []
            for field, (old_v, new_v) in item.get("diffs", {}).items():
                diff_strs.append(
                    f"{field}: <code>{old_v}</code> ➔ <code>{new_v}</code>"
                )
            lines.append(f"• <b>{company}</b>: {', '.join(diff_strs)}")
        if upd_count > 15:
            lines.append(f"  <i>...and {upd_count - 15} more</i>")
        lines.append("")

    # Deleted items section
    if del_count > 0:
        lines.append(f"🗑️ <b>Removed entries ({del_count}):</b>")
        for item in result.get("deleted_items", [])[:15]:
            pay_str = (
                f" (pay: {item['payment_date']})" if item.get("payment_date") else ""
            )
            lines.append(f"• <b>{item['company_name']}</b>{pay_str}")
        if del_count > 15:
            lines.append(f"  <i>...and {del_count - 15} more</i>")

    return "\n".join(lines).strip()


@task
def notify_telegram_task(msg: str) -> bool:
    """
    Prefect task wrapper for sending Telegram messages.
    """
    return send_telegram_notification(msg)


def sync_dividends(
    year: int | None = None,
    db_engine: Engine | None = None,
    send_notification: bool = True,
) -> dict[str, Any]:
    """
    Core engine function: fetches, parses, reconciles, and updates dividends in SQL.

    :param year: The dividend year (defaults to current calendar year).
    :param db_engine: SQLAlchemy Engine. Defaults to connection_manager.postgres_engine.
    :param send_notification: Whether to send Telegram notification.
    :return: Result dictionary with details.
    """
    if year is None:
        year = date.today().year

    if db_engine is None:
        db_engine = connection_manager.postgres_engine

    try:
        html = fetch_dividends_html(year=year)
        scraped_rows = parse_dividends_table(html=html, year=year)
        existing_rows = fetch_existing_dividends(db_engine=db_engine, year=year)

        reconciliation = reconcile_dividends(
            existing_rows=existing_rows, scraped_rows=scraped_rows
        )
        result = execute_dividends_sync(
            db_engine=db_engine, year=year, reconciliation=reconciliation
        )

        msg = format_telegram_message(year=year, result=result)
        if send_notification:
            sent = send_telegram_notification(msg)
            result["telegram_sent"] = sent
        return result

    except Exception as e:
        logger.error(f"Error during dividends sync for year {year}: {e}", exc_info=True)
        result = {"status": "failed", "error": str(e)}
        if send_notification:
            error_msg = format_telegram_message(year=year, result=result)
            send_telegram_notification(error_msg)
        raise


@flow(name="stockwatch-dividends-flow")
def dividends_flow(year: int | None = None) -> dict[str, Any]:
    """
    Prefect flow for scraping and synchronizing StockWatch dividends.

    :param year: The dividend year (defaults to current calendar year).
    :return: Execution summary dictionary.
    """
    target_year = year or date.today().year
    logger.info(
        f"Starting Prefect flow for StockWatch dividends, year {target_year}..."
    )
    db_engine = connection_manager.postgres_engine
    return sync_dividends(year=target_year, db_engine=db_engine, send_notification=True)


def run_standalone() -> None:
    """
    Entry point for CLI standalone execution.
    """
    parser = argparse.ArgumentParser(
        description="Scrape and synchronize StockWatch dividends to PostgreSQL."
    )
    parser.add_argument(
        "--year",
        type=int,
        default=date.today().year,
        help=f"Dividend calendar year to scrape (default: {date.today().year}).",
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Disable sending Telegram notification.",
    )
    args = parser.parse_args()

    print(f"Running StockWatch dividends sync for year {args.year}...")
    result = sync_dividends(year=args.year, send_notification=not args.no_telegram)
    print(
        f"Completed: {result.get('inserted_count', 0)} inserted, "
        f"{result.get('updated_count', 0)} updated, "
        f"{result.get('deleted_count', 0)} deleted, "
        f"{result.get('unchanged_count', 0)} unchanged."
    )


if __name__ == "__main__":
    run_standalone()
