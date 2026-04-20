"""
Main orchestrator for Crown Paradise Club Cancun price monitor.

Usage:
    python main.py                  # Run once immediately
    python main.py --schedule       # Run on schedule
    python main.py --test-email     # Test email connection
    python main.py --config         # Print current config
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
DOCS_DIR = Path("docs")
DOCS_DIR.mkdir(exist_ok=True)

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
STATE_FILE    = DATA_DIR / "last_run.json"
DEALS_FILE    = DATA_DIR / "deals_history.json"
DASHBOARD_FILE = DOCS_DIR / "status.json"   # read by GitHub Pages dashboard


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
    history = history[-500:]
    with open(DEALS_FILE, "w") as f:
        json.dump(history, f, indent=2, default=str)


def write_dashboard_json(state: dict, config: dict, last_deals: list[dict], run_result: dict):
    """Write docs/status.json — read by the GitHub Pages dashboard."""
    # Load full deal history for the dashboard
    history = []
    if DEALS_FILE.exists():
        with open(DEALS_FILE) as f:
            history = json.load(f)

    # Last 20 deals for display
    recent_deals = sorted(history, key=lambda x: x.get("found_at", ""), reverse=True)[:20]

    # Run history: read existing dashboard to append
    existing = {}
    if DASHBOARD_FILE.exists():
        try:
            with open(DASHBOARD_FILE) as f:
                existing = json.load(f)
        except Exception:
            pass

    run_log = existing.get("run_log", [])
    run_log.append({
        "timestamp": state["last_run"],
        "deals_found": run_result.get("deals_found", 0),
        "duration_s": run_result.get("duration_s", 0),
        "error": run_result.get("error"),
    })
    run_log = run_log[-90:]   # keep last 90 runs (~3 weeks)

    payload = {
        "generated_at": datetime.now().isoformat(),
        "config": {
            "hotel": config.get("hotel_name"),
            "route": f"{config.get('departure_city')} → {config.get('destination')}",
            "min_nights": config.get("min_nights"),
            "max_nights": config.get("max_nights"),
            "max_price_cad": config.get("max_price_cad"),
            "monitor_months": config.get("monitor_months_ahead"),
        },
        "stats": {
            "total_runs": state.get("total_runs", 0),
            "total_deals_found": state.get("total_deals_found", 0),
            "last_run": state.get("last_run"),
        },
        "last_run_result": run_result,
        "recent_deals": recent_deals,
        "run_log": run_log,
    }

    with open(DASHBOARD_FILE, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    logger.info(f"📊 Dashboard JSON written to {DASHBOARD_FILE}")


def deals_are_new(deals: list[dict], hours_lookback: int = 6) -> list[dict]:
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
async def run_check(config: dict) -> dict:
    """Execute one monitoring cycle."""
    state = load_state()
    run_start = datetime.now()
    logger.info("=" * 60)
    logger.info(f"🚀 Starting monitoring run #{state['total_runs'] + 1}")
    logger.info(f"   Time: {run_start.strftime('%Y-%m-%d %H:%M:%S ET')}")
    logger.info(f"   Price limit: ${config.get('max_price_cad')} CAD | Months ahead: {config.get('monitor_months_ahead')}")
    logger.info("=" * 60)

    notifier = EmailNotifier(
        gmail_address=config["gmail_address"],
        gmail_app_password=config["gmail_app_password"],
        recipient_email=config["recipient_email"],
    )

    results = {"deals_found": 0, "new_deals": 0, "error": None, "duration_s": 0}

    try:
        monitor = CancunPriceMonitor(config)
        deals = await monitor.run()

        results["deals_found"] = len(deals)
        logger.info(f"📊 Found {len(deals)} qualifying deals (<= ${config.get('max_price_cad')} CAD)")

        if deals:
            save_deals(deals)
            new_deals = deals_are_new(deals)
            results["new_deals"] = len(new_deals)
            if new_deals:
                logger.info(f"📣 Sending email alert for {len(new_deals)} NEW deals!")
                notifier.send_deal_alert(new_deals)
            else:
                logger.info("ℹ️ All deals already notified recently, skipping alert")
        else:
            logger.info(f"😔 No deals found under ${config.get('max_price_cad')} this run")

    except Exception as e:
        logger.error(f"❌ Run failed: {e}", exc_info=True)
        results["error"] = str(e)
        try:
            notifier.send_error_alert(str(e))
        except Exception:
            pass

    # ── Update state & dashboard ──────────────────────────────────────────────
    duration = (datetime.now() - run_start).total_seconds()
    results["duration_s"] = round(duration, 1)

    state["last_run"] = run_start.isoformat()
    state["total_runs"] = state.get("total_runs", 0) + 1
    state["total_deals_found"] = state.get("total_deals_found", 0) + results["deals_found"]
    save_state(state)

    write_dashboard_json(state, config, deals if "deals" in dir() else [], results)

    logger.info(f"✅ Run complete in {duration:.1f}s | Deals found: {results['deals_found']}")
    logger.info("=" * 60)
    return results


# ─── Scheduler ────────────────────────────────────────────────────────────────
async def run_scheduler(config: dict, interval_hours: int = 6):
    logger.info(f"⏰ Scheduler started — running every {interval_hours} hours")
    while True:
        try:
            await run_check(config)
        except Exception as e:
            logger.error(f"Scheduler error: {e}", exc_info=True)
        next_run = datetime.now() + timedelta(hours=interval_hours)
        logger.info(f"💤 Next run: {next_run.strftime('%Y-%m-%d %H:%M:%S ET')}")
        await asyncio.sleep(interval_hours * 3600)


# ─── CLI ──────────────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="Crown Paradise Club Cancun Price Monitor")
    parser.add_argument("--schedule",   action="store_true", help="Run on schedule")
    parser.add_argument("--test-email", action="store_true", help="Send a test email")
    parser.add_argument("--config",     action="store_true", help="Print current config")
    parser.add_argument("--hours", type=int, default=6,  help="Schedule interval in hours")
    args = parser.parse_args()

    config = load_config()

    if args.config:
        safe = {k: ("***" if "password" in k else v) for k, v in config.items()}
        print(json.dumps(safe, indent=2))
        return

    if not config.get("gmail_address") or config["gmail_address"] == "your@gmail.com":
        print("\n⚠️  Gmail not configured. Edit config.json or set GitHub Secrets.\n")
        sys.exit(1)

    if args.test_email:
        notifier = EmailNotifier(config["gmail_address"], config["gmail_app_password"], config["recipient_email"])
        ok = notifier.test_connection()
        print("✅ Test email sent!" if ok else "❌ Email failed — check App Password.")
        return

    if args.schedule:
        await run_scheduler(config, interval_hours=args.hours)
    else:
        await run_check(config)


if __name__ == "__main__":
    asyncio.run(main())
