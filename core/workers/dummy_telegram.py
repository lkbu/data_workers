import os
from prefect import flow, task
import requests

@task
def send_telegram_msg(message: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    requests.post(url, json=payload)

@flow
def my_docker_flow():
    # Your logic here
    send_telegram_msg("🚀 Flow started on Proxmox Docker!")

if __name__ == "__main__":
    my_docker_flow()