"""
Configuration loader for the Cancun Monitor.
Reads from config.json; falls back to environment variables.
"""

import json
import os
from pathlib import Path

CONFIG_FILE = Path("config.json")

DEFAULT_CONFIG = {
    # ── Gmail ─────────────────────────────────────────────────────────────────
    "gmail_address": "your@gmail.com",          # The Gmail account sending alerts
    "gmail_app_password": "xxxx xxxx xxxx xxxx", # 16-char App Password (not real password)
    "recipient_email": "your@gmail.com",         # Where to receive alerts (can be same address)

    # ── Search Parameters ─────────────────────────────────────────────────────
    "departure_city": "YYZ",
    "destination": "CUN",
    "hotel_name": "Crown Paradise Club Cancun",
    "min_nights": 5,
    "max_nights": 7,
    "max_price_cad": 1200,
    "monitor_months_ahead": 3,

    # ── Schedule ──────────────────────────────────────────────────────────────
    "check_interval_hours": 6,

    # ── Browser ──────────────────────────────────────────────────────────────
    "headless": True,
    "request_timeout_ms": 30000,

    # ── Notifications ─────────────────────────────────────────────────────────
    "notify_on_every_deal": False,
}


def load_config() -> dict:
    """Load config from file, environment variables, or defaults."""
    config = DEFAULT_CONFIG.copy()

    # Override with config.json if it exists
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            file_config = json.load(f)
            config.update(file_config)

    # Override with environment variables (useful for Docker/CI)
    env_map = {
        "GMAIL_ADDRESS": "gmail_address",
        "GMAIL_APP_PASSWORD": "gmail_app_password",
        "RECIPIENT_EMAIL": "recipient_email",
        "MAX_PRICE_CAD": "max_price_cad",
        "MIN_NIGHTS": "min_nights",
        "MAX_NIGHTS": "max_nights",
        "MONITOR_MONTHS": "monitor_months_ahead",
        "CHECK_INTERVAL_HOURS": "check_interval_hours",
    }
    for env_key, config_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            # Type coercion
            if config_key in ("max_price_cad", "min_nights", "max_nights",
                              "monitor_months_ahead", "check_interval_hours"):
                config[config_key] = int(val)
            else:
                config[config_key] = val

    return config


def save_config(config: dict):
    """Save config to file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def create_default_config():
    """Create a default config.json for first-time setup."""
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        print(f"✅ Created default config at {CONFIG_FILE}")
        print("   → Edit it to add your Telegram bot token and chat ID")
    else:
        print(f"ℹ️  Config already exists at {CONFIG_FILE}")


if __name__ == "__main__":
    create_default_config()
