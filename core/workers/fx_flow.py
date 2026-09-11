import logging
from prefect import flow, task

from core.data_hub.connection_manager import connection_manager
from core.util.telegram import send_telegram_notification
from core.workers.fx_scraper import upload_fx_data

logger = logging.getLogger(__name__)


def _format_telegram_message(source: str, result: dict) -> str:
    """
    Constructs a clear Telegram message from the scraper result.
    Differentiates between NBP and ECB sources.
    """
    status = result.get("status")
    uploaded_dates = result.get("uploaded_dates", [])
    failed_dates = result.get("failed_dates", [])

    header = f"<b>[FX Scraper - {source.upper()}]</b>"

    if status == "success":
        count = len(uploaded_dates)
        if count <= 5:
            dates_text = ", ".join(uploaded_dates)
        else:
            dates_text = f"{min(uploaded_dates)} to {max(uploaded_dates)}"

        msg_lines = [
            f"✅ {header}",
            f"Uploaded {count} date(s): {dates_text}",
        ]
        if failed_dates:
            msg_lines.append(f"⚠️ Failed periods: {', '.join(failed_dates)}")
        return "\n".join(msg_lines)

    elif status == "no_update":
        return f"ℹ️ {header}\nNothing to update. Data is already up to date."

    elif status == "failed":
        failed_text = ", ".join(failed_dates) if failed_dates else "Unknown error"
        return f"❌ {header}\nFailed to upload data for: {failed_text}"

    return f"ℹ️ {header}\n{result.get('message', 'Completed with unknown status.')}"


@task
def notify_telegram_task(msg: str) -> bool:
    """Prefect task wrapper for sending Telegram messages."""
    return send_telegram_notification(msg)


@flow(name="fx-data-flow")
def fx_data_flow(
    source: str = "NBP",
    start_period: str | None = None,
    end_period: str | None = None,
) -> dict:
    """
    Prefect flow to fetch and upload FX data for a given source (NBP or ECB),
    then send a Telegram notification with the outcome.
    """
    source = source.upper()
    logger.info(f"Starting FX data flow for source: {source}")

    try:
        db_engine = connection_manager.postgres_engine
        result = upload_fx_data(
            source=source,
            db_engine=db_engine,
            start_period=start_period,
            end_period=end_period,
        )
        msg = _format_telegram_message(source, result)
        success = notify_telegram_task(msg)
        result["telegram_sent"] = success
        return result
    except Exception as e:
        error_msg = f"🚨 <b>[FX Scraper - {source}]</b>\nFlow encountered an unexpected error:\n<code>{e}</code>"
        logger.error(f"Error in fx_data_flow for {source}: {e}", exc_info=True)
        send_telegram_notification(error_msg)
        raise


@flow(name="fx-nbp-flow")
def fx_nbp_flow(
    start_period: str | None = None,
    end_period: str | None = None,
) -> dict:
    """Convenience flow specifically for NBP FX rates."""
    return fx_data_flow(source="NBP", start_period=start_period, end_period=end_period)


@flow(name="fx-ecb-flow")
def fx_ecb_flow(
    start_period: str | None = None,
    end_period: str | None = None,
) -> dict:
    """Convenience flow specifically for ECB FX rates."""
    return fx_data_flow(source="ECB", start_period=start_period, end_period=end_period)


if __name__ == "__main__":
    fx_nbp_flow()
