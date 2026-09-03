import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import date, timedelta
import logging
from sqlalchemy import text, engine
from pathlib import Path

from ..sql.sql_reader import read_sql_script

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ecb_all_wildcard_ccy = "https://data-api.ecb.europa.eu/service/data/EXR/D..EUR.SP00.A"
nbp_all_wildcard_ccy = "https://api.nbp.pl/api/exchangerates/tables/A/"

sql_content = read_sql_script(
    Path(__file__).parent.parent / "sql" / "available_data.sql"
)


def upload_fx_data(
    source: str,
    engine: engine.base.Engine | None = None,
    db_params: dict | None = None,
    start_period: date | str | None = None,
    end_period: date | str | None = None,
) -> dict:
    """
    Uploads FX data from a specified source to the database.

    :param source: Data source, either "ECB" or "NBP".
    :param engine: SQLAlchemy engine instance. Defaults to connection_manager.postgres_engine if None.
    :param db_params: Dictionary containing database table name and schema.
    :param start_period: Start date for fetching data.
    :param end_period: End date for fetching data.
    :return: Dictionary containing source, status, uploaded_dates, failed_dates, and message.
    """
    if engine is None:
        from core.data_hub.connection_manager import connection_manager
        engine = connection_manager.postgres_engine

    if db_params is None:
        db_params = {"name": "fx_ts", "schema": "mdh"}

    source = source.upper()
    if source not in ["ECB", "NBP"]:
        raise ValueError("Source must be 'ECB' or 'NBP'")

    if isinstance(start_period, str):
        start_period = date.fromisoformat(start_period)
    if isinstance(end_period, str):
        end_period = date.fromisoformat(end_period)

    df_dict = pd.read_sql(text(sql_content), engine, params={"ts_source": source})
    df_map = pd.read_sql(
        text("select * from mdh.ts_dict where ts_source=:ts_source"),
        engine,
        params={"ts_source": source},
    )

    step_days = 89 if source == "ECB" else 80

    max_date = (
        start_period
        if df_dict.empty or pd.isna(df_dict.max_date.max())
        else df_dict.max_date.max()
    )
    if hasattr(max_date, "date") and not isinstance(max_date, date):
        max_date = max_date.date()
    elif isinstance(max_date, str):
        max_date = date.fromisoformat(max_date)

    if max_date is None:
        raise ValueError(
            f"start_period must be provided when no existing data for {source} is found in database."
        )

    end_period = min(
        end_period or (max_date + timedelta(days=step_days)), date.today()
    )
    start_period = start_period or (max_date + timedelta(days=1))
    if source == "ECB":
        start_period = min(start_period, end_period)

    if start_period >= date.today():
        logger.info(f"Database is already up to date for {source}. Nothing to upload.")
        return {
            "source": source,
            "status": "no_update",
            "uploaded_dates": [],
            "failed_dates": [],
            "message": f"Database is already up to date for {source} (latest date: {max_date}).",
        }

    uploaded_dates = []
    failed_dates = []

    while start_period < date.today():
        chunk_desc = f"{start_period} to {end_period}"
        try:
            if source == "ECB":
                fx_data = get_ecb_fx_rates(
                    start_period=start_period, end_period=end_period, raise_on_error=True
                )
            else:
                fx_data = get_nbp_fx_rates(
                    start_period=start_period, end_period=end_period, raise_on_error=True
                )

            if not fx_data.empty:
                if source == "ECB":
                    fx_data["ts_shortname"] = "EUR" + fx_data["ccy"]
                else:
                    fx_data["ts_shortname"] = fx_data["ccy"] + "PLN"
                fx_data["ts_tenor"] = 0
                fx_data.columns = [col.lower() for col in fx_data.columns]
                fx_data["ts_id"] = fx_data["ts_shortname"].map(
                    df_map.set_index("ts_shortname")["ts_id"]
                )
                fx_data = fx_data[["eod_date", "ts_id", "ts_tenor", "rate"]]
                fx_data.to_sql(
                    name=db_params["name"],
                    con=engine,
                    schema=db_params["schema"],
                    if_exists="append",
                    index=False,
                )
                chunk_dates = sorted(fx_data["eod_date"].dropna().unique())
                for d in chunk_dates:
                    d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                    if d_str not in uploaded_dates:
                        uploaded_dates.append(d_str)
        except Exception as e:
            logger.error(
                f"Error fetching/uploading FX data for {source} ({chunk_desc}): {e}"
            )
            failed_dates.append(chunk_desc)

        if source == "ECB":
            end_period = end_period + timedelta(days=step_days)
        else:
            end_period = min(end_period + timedelta(days=step_days), date.today())

        start_period = start_period + timedelta(days=step_days)

    status = (
        "success" if uploaded_dates else ("failed" if failed_dates else "no_update")
    )
    message = (
        f"Successfully uploaded {len(uploaded_dates)} date(s) for {source}."
        if uploaded_dates
        else (
            "Failed to upload data for specified periods."
            if failed_dates
            else f"No new FX data published for {source}."
        )
    )

    return {
        "source": source,
        "status": status,
        "uploaded_dates": uploaded_dates,
        "failed_dates": failed_dates,
        "message": message,
    }


def get_nbp_fx_rates(
    start_period: date | None = None,
    end_period: date | None = None,
    raise_on_error: bool = False,
) -> pd.DataFrame:
    """
    Calls the NBP API to get daily fx rates for all currencies against PLN.
    Returns a pandas DataFrame with columns: CCY, date, Rate.
    """
    if start_period and end_period:
        nbp_url = f"{nbp_all_wildcard_ccy}{start_period.strftime('%Y-%m-%d')}/{end_period.strftime('%Y-%m-%d')}/"
    elif start_period:
        nbp_url = f"{nbp_all_wildcard_ccy}{start_period.strftime('%Y-%m-%d')}/"
    else:
        nbp_url = nbp_all_wildcard_ccy

    try:
        logger.info(f"Fetching NBP FX data from {nbp_url}")
        # Request XML to use BeautifulSoup parsing with capitalized tags
        response = requests.get(nbp_url, headers={"Accept": "application/xml"})
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching data from NBP API: {e}")
        if raise_on_error:
            raise
        return pd.DataFrame()

    try:
        soup = BeautifulSoup(response.content, "xml")
        tables = soup.find_all("ExchangeRatesTable")

        data = []
        for table in tables:
            effective_date_tag = table.find("EffectiveDate")
            effective_date = effective_date_tag.text if effective_date_tag else None

            rates_tag = table.find("Rates")
            if rates_tag:
                for rate_tag in rates_tag.find_all("Rate"):
                    code_tag = rate_tag.find("Code")
                    ccy = code_tag.text if code_tag else None

                    mid_tag = rate_tag.find("Mid")
                    mid = float(mid_tag.text) if mid_tag else None

                    data.append(
                        {
                            "ccy": ccy,
                            "eod_date": effective_date,
                            "rate": mid,
                        }
                    )

        df = pd.DataFrame(data)
        if not df.empty:
            df["eod_date"] = pd.to_datetime(df["eod_date"]).dt.date
            df["rate"] = df["rate"].astype(float)
        logger.info(f"Successfully parsed NBP FX data. Total rows: {len(df)}")
        return df

    except Exception as e:
        logger.error(f"Failed to parse NBP XML data: {e}")
        if raise_on_error:
            raise
        return pd.DataFrame()


def get_ecb_fx_rates(
    start_period: date | None = None,
    end_period: date | None = None,
    raise_on_error: bool = False,
) -> pd.DataFrame:
    """
    Calls the ECB API to get daily fx rates for all currencies against EUR.
    Returns a pandas DataFrame with columns: CCY, date, Rate.
    """
    params = {}
    if start_period:
        params["startPeriod"] = start_period.strftime("%Y-%m-%d")
    if end_period:
        params["endPeriod"] = end_period.strftime("%Y-%m-%d")

    try:
        logger.info(f"Fetching ECB FX data from {ecb_all_wildcard_ccy}")
        response = requests.get(ecb_all_wildcard_ccy, params=params)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching data from ECB API: {e}")
        if raise_on_error:
            raise
        return pd.DataFrame()

    try:
        soup = BeautifulSoup(response.content, "xml")
        series_list = soup.find_all("Series")

        data = []
        for series in series_list:
            ccy_tag = series.find("Value", id="CURRENCY")
            ccy = ccy_tag.get("value") if ccy_tag else None

            for obs in series.find_all("Obs"):
                obs_dim = obs.find("ObsDimension")
                date_val = obs_dim.get("value") if obs_dim else None

                obs_val = obs.find("ObsValue")
                rate_val = obs_val.get("value") if obs_val else None
                rate_float = (
                    float(rate_val) if isinstance(rate_val, str) and rate_val else None
                )

                data.append(
                    {
                        "ccy": ccy,
                        "eod_date": date_val,
                        "rate": rate_float,
                    }
                )

        df = pd.DataFrame(data)
        if not df.empty:
            df["eod_date"] = pd.to_datetime(df["eod_date"]).dt.date
            df["rate"] = df["rate"].astype(float)
        logger.info(f"Successfully parsed ECB FX data. Total rows: {len(df)}")
        return df

    except Exception as e:
        logger.error(f"Failed to parse ECB XML data: {e}")
        if raise_on_error:
            raise
        return pd.DataFrame()


if __name__ == "__main__":
    test_start = date(2025, 12, 1)
    test_end = date(2025, 12, 31)
    print(f"Testing ECB data fetch from {test_start} to {test_end}...")

    df_rates = get_ecb_fx_rates(start_period=test_start, end_period=test_end)

    if not df_rates.empty:
        print("\nData Preview:")
        print(df_rates.head(10))
        print(f"\nTotal records: {len(df_rates)}")
        print("\nUnique Currencies:")
        print(df_rates["ccy"].unique() if "ccy" in df_rates else "N/A")
    else:
        print("Function returned an empty DataFrame.")

    print(f"Testing NBP data fetch from {test_start} to {test_end}...")

    df_nbp_rates = get_nbp_fx_rates(start_period=test_start, end_period=test_end)

    if not df_nbp_rates.empty:
        print("\nData Preview:")
        print(df_nbp_rates.head(10))
        print(f"\nTotal records: {len(df_nbp_rates)}")
        print("\nUnique Currencies:")
        print(df_nbp_rates["ccy"].unique() if "ccy" in df_nbp_rates else "N/A")
    else:
        print("Function returned an empty DataFrame.")
