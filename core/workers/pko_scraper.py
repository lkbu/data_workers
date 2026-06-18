"""
Module for scraping interest rate data from PKO BP website, including fixed base rates and WIBOR/WIBID rates.
"""
from importlib import resources
from datetime import date, timedelta, datetime
from core.sql.sql_reader import read_sql_script
import json
import urllib.request
import pandas as pd
from sqlalchemy.engine import Engine
from sqlalchemy import text
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sql_content = read_sql_script(
    Path(__file__).parent.parent / "sql" / "available_data.sql"
)


def upload_fixed_base_rate(
    engine: Engine,
    db_params: dict | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
):
    """
    Scrapes the 5-year fixed base rate from PKO BP and uploads it to the database.

    :param engine: SQLAlchemy engine instance.
    :param db_params: Dictionary containing database table name and schema.
    :param start_period: Start date for the scraping period.
    :param end_period: End date for the scraping period.
    """

    if db_params is None:
        db_params = {"name": "fx_ts", "schema": "mdh"}

    df_dict = pd.read_sql(
        text(sql_content), engine, params={"ts_source": "Fixed_base_rate"}
    )
    df_map = pd.read_sql(
        text("select * from mdh.ts_dict where ts_source='Fixed_base_rate'"), engine
    )
    step_days = 30

    end_period = min(
        end_period or (df_dict.max_date.max() + timedelta(days=step_days)), date.today()
    )
    start_period = start_period or (df_dict.max_date.max() + timedelta(days=1))

    rows = []
    current_date = start_period

    while current_date <= end_period:
        try:
            date_str, rate = get_5_year_fixed_base_rate(
                target_date_str=current_date.strftime("%Y-%m-%d")
            )
            if date_str and rate is not None:
                rows.append(
                    {
                        "eod_date": date_str,
                        "ts_shortname": "Fixed_base_rate",
                        "rate": rate,
                    }
                )
        except Exception as e:
            logger.error(f"Error fetching data for date {current_date}: {e}")
            continue

        current_date += timedelta(days=1)

    if not rows:
        logger.warning("No new data found to upload.")
        return

    pko_data = pd.DataFrame(rows)

    # Map ts_id
    pko_data["ts_id"] = pko_data["ts_shortname"].map(
        df_map.set_index("ts_shortname")["ts_id"]
    )

    # Final selection and upload
    pko_data = pko_data[["eod_date", "ts_id", "rate"]]

    pko_data.to_sql(
        name=db_params["name"],
        con=engine,
        schema=db_params["schema"],
        if_exists="append",
        index=False,
    )


def get_5_year_fixed_base_rate(target_date_str="2026-03-31"):
    """
    Fetches the 5-year fixed base rate for a specific date from PKO BP API.

    :param target_date_str: Date in 'YYYY-MM-DD' format.
    :return: Tuple of (formatted_date_str, decimal_rate) or (None, None) if not found.
    """
    # Target date format expected by API
    api_url = (
        f"https://www.pkobp.pl/api/modules/fxrates/fixed/rates?date={target_date_str}"
    )

    req = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.pkobp.pl/waluty?rates",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))

                # The data structure contains "base" for the 5-year fixed base rate
                base_data = data.get("base", {})

                date_str = base_data.get("date")
                value = base_data.get("value")

                if date_str and value is not None:
                    # Convert 'YYYY-MM-DD' to 'DD.MM.YYYY' as requested
                    parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
                    formatted_date = parsed_date.strftime("%d.%m.%Y")

                    # Convert percentage to decimal (4.9 -> 0.049)
                    decimal_value = value / 100.0

                    return formatted_date, decimal_value
                else:
                    logger.warning(f"Data not found in response for date {target_date_str}.")
                    return None, None
            else:
                logger.error(f"Failed to fetch data. HTTP Status: {response.status}")
                return None, None
    except Exception as e:
        logger.error(f"Error fetching data from {api_url}: {e}")
        return None, None


def get_wibor_wibid_rates(target_date_str="2026-03-31"):
    """
    Fetches WIBOR and WIBID interbank rates for a specific date from PKO BP API.

    :param target_date_str: Date in 'YYYY-MM-DD' format.
    :return: Tuple of (dropdown_date, df_wibid, df_wibor) or (None, None, None) if not found.
    """
    api_url = f"https://www.pkobp.pl/api/modules/fxrates/interbank/rates?date={target_date_str}"

    req = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.pkobp.pl/waluty?rates",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))

                dropdown_date = data.get("wibor_s3m", {}).get("date")

                wibid_data = data.get("wibid", {})
                wibor_data = data.get("wibor", {})

                # Create pandas DataFrames
                df_wibid = pd.DataFrame(
                    list(wibid_data.items()),
                    columns=["Okres depozytu", "Wysokość stopy w %"],
                )
                df_wibor = pd.DataFrame(
                    list(wibor_data.items()),
                    columns=["Okres depozytu", "Wysokość stopy w %"],
                )

                # Format date to DD.MM.YYYY
                if dropdown_date:
                    parsed_date = datetime.strptime(dropdown_date, "%Y-%m-%d")
                    dropdown_date = parsed_date.strftime("%d.%m.%Y")

                return dropdown_date, df_wibid, df_wibor
            else:
                logger.error(f"Failed to fetch WIBOR/WIBID. HTTP Status: {response.status}")
                return None, None, None
    except Exception as e:
        logger.error(f"Error fetching WIBOR/WIBID from {api_url}: {e}")
        return None, None, None


if __name__ == "__main__":
    print("-" * 40)
    date_result, rate_result = get_5_year_fixed_base_rate("2021-03-31")
    if date_result:
        print("Found '5-letnia stała stopa bazowa':")
        print(f"Date: {date_result}")
        print(f"Rate: {rate_result}")

    print("-" * 40)
    w_date, wibid_df, wibor_df = get_wibor_wibid_rates("2019-03-28")
    if w_date:
        print(f"WIBOR/WIBID Data from dropdown date: Z dnia {w_date}")
        print("\nWIBID Table:")
        print(wibid_df.to_string(index=False))
        print("\nWIBOR Table:")
        print(wibor_df.to_string(index=False))
    print("-" * 40)
