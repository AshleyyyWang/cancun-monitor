"""
Main orchestrator for Crown Paradise Club Cancun price monitor.
Runs every 4 hours, checks prices, sends Telegram alerts.

Usage:
    python main.py                     # Run once immediately
    python main.py --schedule          # Run on 4-hour schedule
    python main.py --test-telegram     # Test Telegram connection
    python main.py --config            # Print current config
"""

import asyncio
import json
import logging
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

from scraper import CancunPriceMonitor
from notifier import EmailNotifier
from config import load_config, CONFIG_FILE

# ─── Logging Setup ────────────────────────────────────────────────────────────
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

# ─── State Persistence ────────────────────────────────────────────────────────
STATE_FILE = DATA_DIR / "last_run.json"
DEALS_FILE = DATA_DIR / "deals_history.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_run": None, "total_runs": 0, "total_deals_found": 0}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def save_deals(deals: list[dict]):
    history = []
    if DEALS_FILE.exists():
        with open(DEALS_FILE) as f:
            history = json.load(f)

    timestamp = datetime.now().isoformat()
    for deal in deals:
        deal["found_at"] = timestamp
    history.extend(deals)

    # Keep last 500 deals
    history = history[-500:]
    with open(DEALS_FILE, "w") as f:
        json.dump(history, f, indent=2, default=str)


def deals_are_new(deals: list[dict], hours_lookback: int = 4) -> list[dict]:
    """Filter out deals we already notified about recently."""
    if not DEALS_FILE.exists():
        return deals

    with open(DEALS_FILE) as f:
        history = json.load(f)

    cutoff = datetime.now() - timedelta(hours=hours_lookback)
    recent_keys = set()
    for h in history:
        found_at = h.get("found_at")
        if found_at:
            try:
                if datetime.fromisoformat(found_at) > cutoff:
                    key = f"{h.get('departure_date')}_{h.get('nights')}_{h.get('price_per_person')}"
                    recent_keys.add(key)
            except Exception:
                pass

    new_deals = []
    for deal in deals:
        key = f"{deal.get('departure_date')}_{deal.get('nights')}_{deal.get('price_per_person')}"
        if key not in recent_keys:
            new_deals.append(deal)

    logger.info(f"Deals: {len(deals)} total, {len(new_deals)} new (not notified recently)")
    return new_deals


# ─── Core Run Function ────────────────────────────────────────────────────────
async def run_check(config: dict, send_status: bool = False) -> dict:
    """Execute one monitoring cycle."""
    state = load_state()
    run_start = datetime.now()
    logger.info("=" * 60)
    logger.info(f"🚀 Starting monitoring run #{state['total_runs'] + 1}")
    logger.info(f"   Time: {run_start.strftime('%Y-%m-%d %H:%M:%S ET')}")
    logger.info("=" * 60)

    notifier = EmailNotifier(
        gmail_address=config["gmail_address"],
        gmail_app_password=config["gmail_app_password"],
        recipient_email=config["recipient_email"],
    )

    results = {"deals_found": 0, "new_deals": 0, "error": None, "duration_s": 0}

    try:
        # ── Run scraper ───────────────────────────────────────────────────────
        monitor = CancunPriceMonitor(config)
        deals = await monitor.run()

        results["deals_found"] = len(deals)
        logger.info(f"📊 Found {len(deals)} qualifying deals (<= $1,200 CAD)")

        if deals:
            # Save all deals to history
            save_deals(deals)

            # Only notify about genuinely new deals
            new_deals = deals_are_new(deals)
            results["new_deals"] = len(new_deals)

            if new_deals:
                logger.info(f"📣 Sending email alert for {len(new_deals)} NEW deals!")
                notifier.send_deal_alert(new_deals)
            else:
                logger.info("ℹ️ All deals already notified recently, skipping alert")
        else:
            logger.info("😔 No deals found under $1,200 this run")
            # Status updates via email disabled to avoid inbox noise;
            # check logs/ for run history.

    except Exception as e:
        logger.error(f"❌ Run failed: {e}", exc_info=True)
        results["error"] = str(e)
        try:
            notifier.send_error_alert(str(e))
        except Exception:
            pass

    # ── Update state ──────────────────────────────────────────────────────────
    duration = (datetime.now() - run_start).total_seconds()
    results["duration_s"] = round(duration, 1)

    state["last_run"] = run_start.isoformat()
    state["total_runs"] = state.get("total_runs", 0) + 1
    state["total_deals_found"] = state.get("total_deals_found", 0) + results["deals_found"]
    save_state(state)

    logger.info(f"✅ Run complete in {duration:.1f}s | Deals found: {results['deals_found']}")
    logger.info("=" * 60)
    return results


# ─── Scheduler ────────────────────────────────────────────────────────────────
async def run_scheduler(config: dict, interval_hours: int = 4):
    """Run the monitor on a fixed schedule."""
    logger.info(f"⏰ Scheduler started — running every {interval_hours} hours")
    run_count = 0

    while True:
        try:
            # Send status update every 3rd run (every 12 hours)
            send_status = run_count % 3 == 0
            await run_check(config, send_status=send_status)
            run_count += 1
        except Exception as e:
            logger.error(f"Scheduler error: {e}", exc_info=True)

        next_run = datetime.now() + timedelta(hours=interval_hours)
        logger.info(f"💤 Next run scheduled for: {next_run.strftime('%Y-%m-%d %H:%M:%S ET')}")
        await asyncio.sleep(interval_hours * 3600)


# ─── CLI Entry Point ──────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(
        description="Crown Paradise Club Cancun Price Monitor"
    )
    parser.add_argument("--schedule", action="store_true", help="Run on 4-hour schedule")
    parser.add_argument("--test-telegram", action="store_true", help="Test Telegram connection")
    parser.add_argument("--config", action="store_true", help="Print current configuration")
    parser.add_argument("--hours", type=int, default=4, help="Schedule interval in hours (default: 4)")
    parser.add_argument("--status", action="store_true", help="Send status update even if no deals")
    args = parser.parse_args()

    # Load config
    config = load_config()

    if args.config:
        print("\n📋 Current Configuration:")
        safe_config = {k: ("***" if "token" in k or "id" in k else v) for k, v in config.items()}
        print(json.dumps(safe_config, indent=2))
        return

    if not config.get("gmail_address") or config["gmail_address"] == "your@gmail.com":
        print("\n⚠️  ERROR: Gmail address not configured!")
        print(f"   Edit {CONFIG_FILE} and set gmail_address, gmail_app_password, recipient_email.")
        print("   See README for App Password setup instructions.\n")
        sys.exit(1)

    if args.test_telegram:
        print("📧 Testing Gmail connection...")
        notifier = EmailNotifier(
            gmail_address=config["gmail_address"],
            gmail_app_password=config["gmail_app_password"],
            recipient_email=config["recipient_email"],
        )
        success = notifier.test_connection()
        if success:
            print(f"✅ Test email sent to {config['recipient_email']}!")
        else:
            print("❌ Email send FAILED. Check your gmail_address and gmail_app_password in config.json.")
        return

    if args.schedule:
        await run_scheduler(config, interval_hours=args.hours)
    else:
        # Single run
        await run_check(config, send_status=args.status)


if __name__ == "__main__":
    asyncio.run(main())
