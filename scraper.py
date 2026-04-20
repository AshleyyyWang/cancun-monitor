"""
Crown Paradise Club Cancun - Price Monitor
Monitors Redtag.ca for YYZ → Cancun all-inclusive packages
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────
HOTEL_NAME = "Crown Paradise Club Cancun"
DEPARTURE_CITY = "YYZ"
DESTINATION = "CUN"
MIN_NIGHTS = 5
MAX_NIGHTS = 7
MAX_PRICE_CAD = 1200
MONITOR_MONTHS_AHEAD = 3

# Redtag direct hotel URL (all-inclusive packages)
REDTAG_BASE_URL = "https://www.redtag.ca/vacations/mexico/cancun/crown-paradise-club-cancun"
REDTAG_SEARCH_URL = (
    "https://www.redtag.ca/vacations/search"
    "?from=YYZ&to=CUN&hotel=crown-paradise-club-cancun"
    "&nights=5,6,7&board=AI"
)

# Sunwing fallback
SUNWING_BASE_URL = (
    "https://www.sunwing.ca/en/vacation-packages/mexico/cancun"
    "?hotel=crown-paradise-club-cancun&from=YYZ"
    "&nights=5-7&mealplan=all-inclusive"
)


class CancunPriceMonitor:
    def __init__(self, config: dict):
        self.config = config
        self.results: list[dict] = []
        self.browser: Optional[Browser] = None

    # ─── Browser Setup ────────────────────────────────────────────────────────
    async def _launch_browser(self, playwright):
        self.browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-CA",
        )
        return context

    # ─── Redtag Scraper ───────────────────────────────────────────────────────
    async def scrape_redtag(self) -> list[dict]:
        """Scrape Redtag.ca for Crown Paradise Club Cancun deals."""
        deals = []
        logger.info("🔍 Starting Redtag.ca scrape...")

        async with async_playwright() as p:
            context = await self._launch_browser(p)
            page = await context.new_page()

            try:
                # ── Step 1: Load hotel page ──────────────────────────────────
                logger.info(f"Navigating to: {REDTAG_BASE_URL}")
                await page.goto(REDTAG_BASE_URL, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)

                # Accept cookies if present
                await self._dismiss_overlays(page)

                # ── Step 2: Look for "Lowest Price Calendar" button ──────────
                calendar_opened = await self._open_price_calendar(page)

                if calendar_opened:
                    logger.info("✅ Price calendar opened, extracting calendar deals...")
                    calendar_deals = await self._extract_calendar_prices(page)
                    deals.extend(calendar_deals)

                # ── Step 3: Also scrape the standard listing ─────────────────
                listing_deals = await self._extract_listing_prices(page)
                deals.extend(listing_deals)

                # ── Step 4: If no results, try search URL ────────────────────
                if not deals:
                    logger.info("No results on hotel page, trying search URL...")
                    await page.goto(REDTAG_SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                    await self._dismiss_overlays(page)
                    listing_deals = await self._extract_listing_prices(page)
                    deals.extend(listing_deals)

            except Exception as e:
                logger.error(f"Redtag scrape error: {e}", exc_info=True)
            finally:
                await page.close()
                await context.close()
                await self.browser.close()

        logger.info(f"Redtag found {len(deals)} raw deals")
        return deals

    async def _dismiss_overlays(self, page: Page):
        """Dismiss cookie banners, popups, etc."""
        selectors = [
            "button[id*='accept']",
            "button[class*='accept']",
            "button[class*='cookie']",
            "[data-testid='cookie-accept']",
            ".modal-close",
            ".popup-close",
            "button:has-text('Accept')",
            "button:has-text('Got it')",
            "button:has-text('Close')",
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    await page.wait_for_timeout(500)
                    logger.debug(f"Dismissed overlay: {sel}")
                    break
            except Exception:
                pass

    async def _open_price_calendar(self, page: Page) -> bool:
        """Try to click the 'Lowest Price Calendar' or similar calendar button."""
        calendar_selectors = [
            # Redtag-specific
            "button:has-text('Lowest Price Calendar')",
            "button:has-text('Price Calendar')",
            "a:has-text('Lowest Price Calendar')",
            "[class*='price-calendar']",
            "[class*='lowest-price']",
            "[data-tab='calendar']",
            # Generic calendar tabs
            "button:has-text('Calendar')",
            "[role='tab']:has-text('Calendar')",
            ".tab:has-text('Calendar')",
        ]

        for sel in calendar_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    logger.info(f"✅ Opened calendar via: {sel}")
                    return True
            except Exception:
                pass

        logger.info("ℹ️ Calendar button not found, continuing with listing view")
        return False

    async def _extract_calendar_prices(self, page: Page) -> list[dict]:
        """Extract prices from the lowest-price calendar grid."""
        deals = []

        # Wait for calendar to load
        await page.wait_for_timeout(2000)

        # Try to find calendar cells with prices
        calendar_cells = await page.query_selector_all(
            "[class*='calendar'] [class*='price'], "
            "[class*='calendar-day'], "
            "[class*='price-cell'], "
            "td[data-date]"
        )

        logger.info(f"Found {len(calendar_cells)} calendar cells")

        for cell in calendar_cells:
            try:
                text = await cell.inner_text()
                date_attr = await cell.get_attribute("data-date") or ""
                price = self._parse_price(text)
                date = self._parse_date(date_attr or text)

                if price and date and price <= MAX_PRICE_CAD:
                    # Try to get nights info from cell or nearby element
                    nights = await self._extract_nights_from_cell(cell, page)
                    if MIN_NIGHTS <= nights <= MAX_NIGHTS:
                        booking_url = await self._build_booking_url(page, date, nights)
                        deals.append({
                            "hotel": HOTEL_NAME,
                            "departure_date": date,
                            "nights": nights,
                            "price_per_person": price,
                            "source": "redtag_calendar",
                            "booking_url": booking_url,
                        })
            except Exception:
                pass

        return deals

    async def _extract_listing_prices(self, page: Page) -> list[dict]:
        """Extract prices from standard hotel/package listings."""
        deals = []
        found_hotel = False

        # Collect all price-containing elements
        price_selectors = [
            # Redtag-specific classes
            "[class*='price-amount']",
            "[class*='package-price']",
            "[class*='deal-price']",
            "[class*='pricepp']",
            "[class*='total-price']",
            # Generic
            "[data-price]",
            ".price",
            "span:has-text('$')",
        ]

        # First check if hotel name appears on page
        try:
            content = await page.content()
            if HOTEL_NAME.lower() in content.lower() or "crown paradise" in content.lower():
                found_hotel = True
                logger.info(f"✅ Found {HOTEL_NAME} on page")
        except Exception:
            pass

        # Extract from package cards
        package_cards = await page.query_selector_all(
            "[class*='package-card'], "
            "[class*='deal-card'], "
            "[class*='hotel-card'], "
            "[class*='result-item'], "
            "[class*='search-result']"
        )

        if not package_cards:
            # Fallback: try to parse the full page
            package_cards = await page.query_selector_all("article, .card, li[class*='result']")

        logger.info(f"Found {len(package_cards)} package cards")

        for card in package_cards:
            try:
                card_text = await card.inner_text()

                # Verify this card is for Crown Paradise Club Cancun
                card_lower = card_text.lower()
                if "crown paradise" not in card_lower and found_hotel is False:
                    continue

                # Extract price
                price = self._extract_price_from_element(card_text)
                if not price:
                    # Try data attributes
                    price_attr = await card.get_attribute("data-price")
                    if price_attr:
                        price = float(re.sub(r"[^\d.]", "", price_attr))

                if not price or price > MAX_PRICE_CAD:
                    continue

                # Extract date
                date = self._extract_date_from_text(card_text)
                if not date:
                    continue

                # Extract nights
                nights_match = re.search(r"(\d+)\s*night", card_text, re.IGNORECASE)
                nights = int(nights_match.group(1)) if nights_match else 7

                if not (MIN_NIGHTS <= nights <= MAX_NIGHTS):
                    continue

                # Extract/build booking URL
                booking_url = await self._extract_booking_url(card) or await self._build_booking_url(page, date, nights)

                deals.append({
                    "hotel": HOTEL_NAME,
                    "departure_date": date,
                    "nights": nights,
                    "price_per_person": price,
                    "source": "redtag_listing",
                    "booking_url": booking_url,
                })

            except Exception as e:
                logger.debug(f"Card parse error: {e}")

        # ── Shadow DOM / iframe fallback ─────────────────────────────────────
        shadow_deals = await self._handle_shadow_dom_or_iframe(page)
        deals.extend(shadow_deals)

        return deals

    async def _handle_shadow_dom_or_iframe(self, page: Page) -> list[dict]:
        """Handle prices inside Shadow DOM or iframes."""
        deals = []

        # Check for iframes
        frames = page.frames
        logger.info(f"Found {len(frames)} frames on page")

        for frame in frames[1:]:  # Skip main frame
            try:
                frame_url = frame.url
                if any(x in frame_url for x in ["redtag", "sunwing", "booking", "vacation"]):
                    logger.info(f"Checking iframe: {frame_url}")
                    content = await frame.content()
                    prices = self._extract_all_prices(content)
                    for price_info in prices:
                        if price_info.get("price", 0) <= MAX_PRICE_CAD:
                            price_info["source"] = "redtag_iframe"
                            deals.append(price_info)
            except Exception:
                pass

        # Shadow DOM via JavaScript evaluation
        try:
            shadow_prices = await page.evaluate("""
                () => {
                    const results = [];
                    function searchShadowDOM(root) {
                        const priceEls = root.querySelectorAll(
                            '[class*="price"], [class*="amount"], [data-price]'
                        );
                        priceEls.forEach(el => {
                            const text = el.textContent || '';
                            const match = text.match(/\\$([\\d,]+(?:\\.\\d{2})?)/);
                            if (match) {
                                const price = parseFloat(match[1].replace(',', ''));
                                if (price > 0 && price < 5000) {
                                    results.push({
                                        text: text.trim().substring(0, 200),
                                        price: price,
                                        className: el.className
                                    });
                                }
                            }
                        });
                        // Recurse into shadow roots
                        root.querySelectorAll('*').forEach(el => {
                            if (el.shadowRoot) searchShadowDOM(el.shadowRoot);
                        });
                    }
                    searchShadowDOM(document);
                    return results;
                }
            """)

            if shadow_prices:
                logger.info(f"Shadow DOM found {len(shadow_prices)} price elements")
                for item in shadow_prices:
                    if item["price"] <= MAX_PRICE_CAD:
                        deals.append({
                            "hotel": HOTEL_NAME,
                            "departure_date": None,
                            "nights": 7,
                            "price_per_person": item["price"],
                            "source": "shadow_dom",
                            "booking_url": REDTAG_BASE_URL,
                        })
        except Exception as e:
            logger.debug(f"Shadow DOM eval error: {e}")

        return deals

    # ─── Sunwing Fallback ─────────────────────────────────────────────────────
    async def scrape_sunwing(self) -> list[dict]:
        """Fallback: scrape Sunwing for the same hotel."""
        deals = []
        logger.info("🔍 Starting Sunwing fallback scrape...")

        async with async_playwright() as p:
            context = await self._launch_browser(p)
            page = await context.new_page()

            try:
                await page.goto(SUNWING_BASE_URL, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
                await self._dismiss_overlays(page)

                listing_deals = await self._extract_listing_prices(page)
                for d in listing_deals:
                    d["source"] = "sunwing_listing"
                deals.extend(listing_deals)

            except Exception as e:
                logger.error(f"Sunwing scrape error: {e}")
            finally:
                await page.close()
                await context.close()
                await self.browser.close()

        logger.info(f"Sunwing found {len(deals)} raw deals")
        return deals

    # ─── Helper: Price Parsing ────────────────────────────────────────────────
    def _parse_price(self, text: str) -> Optional[float]:
        if not text:
            return None
        # Match patterns like $999, $1,199.00, 1199 pp
        patterns = [
            r"\$\s*([\d,]+(?:\.\d{2})?)",
            r"([\d,]+(?:\.\d{2})?)\s*(?:CAD|pp|per person)",
            r"([\d]{3,4})(?:\.\d{2})?",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                price = float(m.group(1).replace(",", ""))
                if 200 < price < 5000:
                    return price
        return None

    def _extract_price_from_element(self, text: str) -> Optional[float]:
        """Extract 'taxes & fees included' price from element text."""
        # Look for "taxes included" context
        tax_patterns = [
            r"\$([\d,]+(?:\.\d{2})?)\s*(?:CAD\s*)?(?:per person|pp)\s*(?:taxes|incl)",
            r"([\d,]+(?:\.\d{2})?)\s*pp\s*\*?taxes\s*(?:&|and)\s*fees\s*incl",
            r"\$([\d,]+(?:\.\d{2})?)",
        ]
        for pat in tax_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                price = float(m.group(1).replace(",", ""))
                if 200 < price < 5000:
                    return price
        return None

    def _parse_date(self, text: str) -> Optional[str]:
        if not text:
            return None
        patterns = [
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{2}/\d{2}/\d{4})",
            r"(\w{3,9}\s+\d{1,2},?\s+\d{4})",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                raw = m.group(1)
                for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"]:
                    try:
                        dt = datetime.strptime(raw, fmt)
                        return dt.strftime("%Y-%m-%d")
                    except ValueError:
                        pass
        return None

    def _extract_date_from_text(self, text: str) -> Optional[str]:
        patterns = [
            r"(\w{3,9}\.?\s+\d{1,2})",  # "Jan 15", "December 3"
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{1,2}/\d{1,2}/\d{4})",
        ]
        year = datetime.now().year
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                raw = m.group(1)
                for fmt in ["%b %d", "%B %d", "%B. %d"]:
                    try:
                        dt = datetime.strptime(f"{raw} {year}", f"{fmt} %Y")
                        # Handle year rollover
                        if dt < datetime.now() - timedelta(days=30):
                            dt = dt.replace(year=year + 1)
                        return dt.strftime("%Y-%m-%d")
                    except ValueError:
                        pass
        return None

    def _extract_all_prices(self, html_content: str) -> list[dict]:
        """Parse raw HTML for any price-like patterns."""
        results = []
        price_pattern = re.compile(r"\$([\d,]+(?:\.\d{2})?)", re.IGNORECASE)
        for m in price_pattern.finditer(html_content):
            price = float(m.group(1).replace(",", ""))
            if 200 < price <= MAX_PRICE_CAD:
                results.append({"price": price})
        return results

    async def _extract_nights_from_cell(self, cell, page: Page) -> int:
        """Try to get nights from a calendar cell or its context."""
        try:
            # Check data attributes
            nights_attr = await cell.get_attribute("data-nights")
            if nights_attr:
                return int(nights_attr)
            # Check nearby text
            parent = await cell.evaluate_handle("el => el.closest('[data-nights]')")
            if parent:
                nights = await parent.get_attribute("data-nights")
                if nights:
                    return int(nights)
        except Exception:
            pass
        return 7  # Default to 7 nights

    async def _extract_booking_url(self, element) -> Optional[str]:
        """Extract booking URL from a card element."""
        try:
            link = await element.query_selector("a[href*='redtag'], a[href*='sunwing'], a[href*='book']")
            if link:
                href = await link.get_attribute("href")
                if href:
                    if href.startswith("/"):
                        return f"https://www.redtag.ca{href}"
                    return href
        except Exception:
            pass
        return None

    async def _build_booking_url(self, page: Page, date: Optional[str], nights: int) -> str:
        """Build a direct booking URL for the hotel + date."""
        if not date:
            return REDTAG_BASE_URL
        # Construct Redtag deep-link
        url = (
            f"https://www.redtag.ca/vacations/mexico/cancun/crown-paradise-club-cancun"
            f"?from=YYZ&nights={nights}&depDate={date}&adults=2&board=AI"
        )
        return url

    # ─── Main Run ─────────────────────────────────────────────────────────────
    async def run(self) -> list[dict]:
        """Run the full scrape and return filtered deals."""
        all_deals = []

        # Primary: Redtag
        redtag_deals = await self.scrape_redtag()
        all_deals.extend(redtag_deals)

        # Fallback: Sunwing
        if not all_deals:
            logger.info("No Redtag results, trying Sunwing...")
            sunwing_deals = await self.scrape_sunwing()
            all_deals.extend(sunwing_deals)

        # Filter and deduplicate
        filtered = self._filter_deals(all_deals)
        logger.info(f"✅ Final filtered deals: {len(filtered)}")
        return filtered

    def _filter_deals(self, deals: list[dict]) -> list[dict]:
        """Apply all filters: price, nights, date range, deduplicate."""
        now = datetime.now()
        cutoff = now + timedelta(days=MONITOR_MONTHS_AHEAD * 30)

        filtered = []
        seen = set()

        for deal in deals:
            try:
                price = deal.get("price_per_person", 0)
                nights = deal.get("nights", 0)
                date_str = deal.get("departure_date")

                # Price filter
                if not price or price > MAX_PRICE_CAD:
                    continue

                # Nights filter
                if not (MIN_NIGHTS <= nights <= MAX_NIGHTS):
                    continue

                # Date filter
                if date_str:
                    try:
                        dep_date = datetime.strptime(date_str, "%Y-%m-%d")
                        if dep_date < now or dep_date > cutoff:
                            continue
                    except ValueError:
                        pass

                # Dedup key
                key = f"{date_str}_{nights}_{price}"
                if key in seen:
                    continue
                seen.add(key)

                filtered.append(deal)

            except Exception as e:
                logger.debug(f"Filter error: {e}")

        # Sort by price
        filtered.sort(key=lambda x: x.get("price_per_person", 9999))
        return filtered
