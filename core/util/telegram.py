import logging
import os
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def send_telegram_notification(msg: str) -> bool:
    """
    Sends a message to Telegram using bot credentials from environment variables:
    - TELEGRAM_BOT_TOKEN
    - TELEGRAM_CHAT_ID

    :param msg: The message content to send.
    :return: True if sent successfully, False otherwise.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in environment. Skipping Telegram notification."
        )
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg}

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Telegram notification sent successfully.")
            return True
        else:
            logger.error(
                f"Telegram API request failed with status code {response.status_code}: {response.text}"
            )
            return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error sending Telegram notification: {e}")
        return False
