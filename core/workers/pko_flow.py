import logging
from prefect import flow, task

from core.data_hub.connection_manager import connection_manager
from core.util.telegram import send_telegram_notification
from core.workers.pko_scraper import upload_fixed_base_rate

logger = logging.getLogger(__name__)


def _format_telegram_message(result: dict) -> str:
    """
    Constructs a clear Telegram message from the PKO scraper result.
    """
    status = result.get("status")
    uploaded_dates = result.get("uploaded_dates", [])
    failed_dates = result.get("failed_dates", [])

    header = "<b>[PKO Scraper - Fixed Base Rate]</b>"

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
            msg_lines.append(f"⚠️ Failed dates: {', '.join(failed_dates)}")
        return "\n".join(msg_lines)

    elif status == "no_update":
        return f"ℹ️ {header}\nNothing to update. Database is already up to date."

    elif status == "failed":
        failed_text = ", ".join(failed_dates) if failed_dates else "Unknown error"
        return f"❌ {header}\nFailed to upload dates: {failed_text}"

    return f"ℹ️ {header}\n{result.get('message', 'Completed with unknown status.')}"


@task
def notify_telegram_task(msg: str):
    """Prefect task wrapper for sending Telegram messages."""
    send_telegram_notification(msg)


@flow(name="pko-fixed-base-rate-flow")
def pko_fixed_base_rate_flow(
    start_period: str | None = None,
    end_period: str | None = None,
) -> dict:
    """
    Prefect flow to fetch and upload PKO BP 5-year fixed base rates,
    then send a Telegram notification with the outcome.
    """
    logger.info("Starting PKO BP fixed base rate flow...")

    try:
        db_engine = connection_manager.postgres_engine
        result = upload_fixed_base_rate(
            db_engine=db_engine,
            start_period=start_period,
            end_period=end_period,
        )
        msg = _format_telegram_message(result)
        notify_telegram_task(msg)
        return result
    except Exception as e:
        error_msg = f"🚨 <b>[PKO Scraper - Fixed Base Rate]</b>\nFlow encountered an unexpected error:\n<code>{e}</code>"
        logger.error(f"Error in pko_fixed_base_rate_flow: {e}", exc_info=True)
        send_telegram_notification(error_msg)
        raise


if __name__ == "__main__":
    pko_fixed_base_rate_flow()
