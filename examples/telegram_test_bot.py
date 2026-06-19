import os
import requests

def test_telegram_notification():
    # 1. Grab variables from environment
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    # Quick sanity check
    if not token or not chat_id:
        print("❌ Error: Missing environment variables!")
        print("Make sure to export them first via your terminal:")
        print("export TELEGRAM_BOT_TOKEN='your_token_here'")
        print("export TELEGRAM_CHAT_ID='your_chat_id_here'\n")
        return

    # 2. Construct API URL and payload
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "👋 Hello from Proxmox! The standalone network test worked."
    }
    
    print("Sending test message...")
    
    # 3. Hit the Telegram API
    try:
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            print("✅ Success! Check your Telegram app.")
        else:
            print(f"❌ Failed with status code: {response.status_code}")
            print(f"Response details: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print("❌ Network Error: Could not connect to Telegram API.")
        print(f"Details: {e}")

if __name__ == "__main__":
    test_telegram_notification()