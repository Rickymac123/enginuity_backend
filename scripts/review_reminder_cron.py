import os
import sys
import requests

def main() -> int:
    url = os.environ.get("CRON_TARGET_URL")
    secret = os.environ.get("REMINDER_JOB_SECRET")
    if not url or not secret:
        print("Missing CRON_TARGET_URL or REMINDER_JOB_SECRET")
        return 2

    r = requests.post(url, headers={"X-Job-Secret": secret}, timeout=20)
    print("status:", r.status_code)
    print("body:", r.text)
    return 0 if r.ok else 1

if __name__ == "__main__":
    raise SystemExit(main())