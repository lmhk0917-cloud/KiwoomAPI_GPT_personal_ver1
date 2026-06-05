"""Send a standalone Telegram test message.

Required environment variables, or equivalent entries in local .env:

TELEGRAM_BOT_TOKEN=put_your_telegram_bot_token_here
TELEGRAM_CHAT_ID=put_your_chat_id_here
"""

import argparse
import json
from datetime import datetime

from notifier import Notifier


def parse_args():
    parser = argparse.ArgumentParser(description="Send a Telegram test notification.")
    parser.add_argument(
        "--message",
        default=None,
        help="Message text to send. A timestamped default is used when omitted.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    message = args.message or "Kiwoom/OpenAI Telegram test {}".format(
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    notifier = Notifier(settings={
        "ENABLE_NOTIFICATIONS": True,
        "NOTIFICATION_CHANNELS": ["telegram"],
    })
    results = notifier.notify_text(message, channels=["telegram"])

    print(json.dumps(results, ensure_ascii=False, indent=2))

    failed = [
        result for result in results
        if result.get("status") not in ("success", "skipped")
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
