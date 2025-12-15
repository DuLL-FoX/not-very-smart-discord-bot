from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import aiohttp

from .constants import DTEK_REGIONS, SHUTDOWNS_PATH, AJAX_PATH, USER_AGENT, STATUS_LABELS
from .models import ScheduleData, NetworkException, ParsingException, ValidationException

logger = logging.getLogger("dtek_cog.scraper")


def _pick_queue(house_data: Dict, house_number: str) -> str:
    if house_number not in house_data:
        available = ", ".join(sorted(house_data.keys()))
        raise ValidationException(
            f"House number '{house_number}' not found in the address lookup results.\n"
            f"Available house numbers: {available}\n"
            f"Please check that you specified the correct house number."
        )
    queue_codes = house_data[house_number].get("sub_type_reason") or []
    if not queue_codes:
        raise ValidationException(
            f"No queue mapping returned for house number '{house_number}'. "
            f"This address may not have shutdown schedule data available."
        )
    return queue_codes[0]


def _format_time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _compress_day_detailed(periods: Dict[str, str]) -> List[Tuple[str, str, str]]:
    status_map = {
        "yes": ("yes", "yes"),
        "no": ("no", "no"),
        "first": ("no", "yes"),
        "second": ("yes", "no"),
        "maybe": ("maybe", "maybe"),
        "mfirst": ("maybe", "yes"),
        "msecond": ("yes", "maybe"),
    }

    blocks: List[Tuple[int, int, str]] = []
    sorted_slots = sorted((int(k), v) for k, v in periods.items())

    for slot_number, status in sorted_slots:
        hour = slot_number - 1
        s1, s2 = status_map.get(status, (status, status))
        blocks.append((hour, 0, s1))
        blocks.append((hour, 30, s2))

    compressed: List[Tuple[str, str, str]] = []
    if not blocks:
        return compressed

    current_start_h, current_start_m, current_status = blocks[0]

    for i in range(1, len(blocks)):
        h, m, status = blocks[i]
        if status != current_status:
            compressed.append((
                _format_time(current_start_h, current_start_m),
                _format_time(h, m),
                current_status
            ))
            current_start_h, current_start_m = h, m
            current_status = status

    last_h, last_m, _ = blocks[-1]
    end_m = last_m + 30
    end_h = last_h
    if end_m >= 60:
        end_m -= 60
        end_h += 1

    compressed.append((
        _format_time(current_start_h, current_start_m),
        _format_time(end_h, end_m),
        current_status
    ))

    return compressed


class ScraperService:
    def __init__(self):
        self._cache: Dict[str, ScheduleData] = {}
        self._scraper_lock = asyncio.Lock()

    def clear_cache(self):
        self._cache.clear()

    def clear_scrapers(self):
        pass

    def get_cache(self, region: str) -> Optional[ScheduleData]:
        return self._cache.get(region)

    async def _fetch_with_browser(self, base_url: str, headless: bool = True, page_timeout: int = 30000) -> Tuple[str, str]:
        logger.info(f"[SCRAPER] _fetch_with_browser called for base_url={base_url}, headless={headless}, timeout={page_timeout}")

        try:
            logger.debug(f"[SCRAPER] Importing Camoufox...")
            from camoufox.async_api import AsyncCamoufox
            logger.debug(f"[SCRAPER] Camoufox imported successfully")
        except ImportError as exc:
            logger.exception(f"[SCRAPER] CRITICAL: Camoufox import failed")
            raise RuntimeError("Camoufox is required. Install it via 'pip install camoufox'.") from exc

        logger.info(f"[SCRAPER] Launching Camoufox browser (headless={headless})...")

        firefox_prefs = {
            "network.dns.disablePrefetch": True,
            "network.dns.disableIPv6": False,
            "network.proxy.type": 0,
        }

        browser_instance = None
        page = None

        try:
            logger.debug(f"[SCRAPER] Creating AsyncCamoufox instance...")
            async with AsyncCamoufox(headless=headless, firefox_user_prefs=firefox_prefs) as browser_instance:
                logger.info(f"[SCRAPER] Browser instance created successfully")

                logger.debug(f"[SCRAPER] Creating new page...")
                page = await browser_instance.new_page()
                logger.info(f"[SCRAPER] New page created")

                try:
                    target_url = f"{base_url}{SHUTDOWNS_PATH}"
                    logger.info(f"[SCRAPER] Navigating to {target_url}...")
                    await page.goto(
                        target_url,
                        wait_until="domcontentloaded",
                        timeout=30000
                    )
                    logger.info(f"[SCRAPER] Page loaded (domcontentloaded)")

                    logger.debug(f"[SCRAPER] Waiting for selector #discon_form...")
                    await page.wait_for_selector("#discon_form", timeout=page_timeout)
                    logger.info(f"[SCRAPER] Selector #discon_form found")

                    logger.debug(f"[SCRAPER] Waiting for networkidle state...")
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    logger.info(f"[SCRAPER] Network idle state reached")

                    logger.debug(f"[SCRAPER] Extracting page content...")
                    html = await page.content()
                    logger.info(f"[SCRAPER] Page content extracted, length={len(html)} chars")

                    logger.debug(f"[SCRAPER] Extracting cookies...")
                    context = page.context
                    cookies = await context.cookies()
                    cookie_header = "; ".join(
                        f"{cookie.get('name', '')}={cookie.get('value', '')}"
                        for cookie in cookies
                        if cookie.get('name')
                    )
                    logger.info(f"[SCRAPER] Extracted {len(cookies)} cookies")

                    logger.info(f"[SCRAPER] Browser fetch completed successfully")
                    return html, cookie_header

                except asyncio.TimeoutError as e:
                    logger.exception(f"[SCRAPER] CRITICAL: Browser operation timed out: {e}")
                    raise
                except Exception as e:
                    logger.exception(f"[SCRAPER] CRITICAL: Browser page operation failed: {type(e).__name__}: {e}")
                    raise
                finally:
                    if page:
                        try:
                            logger.debug(f"[SCRAPER] Closing page...")
                            await page.close()
                            logger.debug(f"[SCRAPER] Page closed")
                        except Exception as e:
                            logger.warning(f"[SCRAPER] Error closing page: {e}")

        except Exception as e:
            logger.exception(f"[SCRAPER] CRITICAL: Browser automation failed: {type(e).__name__}: {e}")
            raise
        finally:
            logger.debug(f"[SCRAPER] _fetch_with_browser exiting")

    def _extract_between(self, html: str, start: str, end_pattern: str) -> str:
        pattern = rf"{re.escape(start)}\s*(\{{.*?\}})\s*(?={end_pattern})"
        match = re.search(pattern, html, re.S)
        if not match:
            raise ParsingException(
                f"Unable to locate JSON blob for {start!r}. "
                f"The page structure may have changed, or the page did not load correctly."
            )
        return match.group(1)

    def _parse_schedule_from_html(self, html: str, cookie: str) -> ScheduleData:
        csrf_match = re.search(
            r'<meta\s+name="csrf-token"\s+content="([^"]+)"', html, re.I
        )
        if not csrf_match:
            raise ParsingException(
                "CSRF token meta tag not found in page. "
                "The page may not have loaded correctly."
            )
        csrf_token = csrf_match.group(1)

        try:
            preset_json = self._extract_between(
                html, "DisconSchedule.preset =", r"DisconSchedule\.showCurOutage"
            )
            fact_json = self._extract_between(
                html, "DisconSchedule.fact =", r"</script>"
            )

            preset = json.loads(preset_json)
            fact = json.loads(fact_json)
        except ParsingException:
            raise
        except json.JSONDecodeError as e:
            raise ParsingException(
                f"Failed to parse JSON data from HTML: {e}. "
                f"The data format may have changed."
            ) from e

        return ScheduleData(preset=preset, fact=fact, csrf_token=csrf_token, cookie=cookie)

    async def fetch_schedule_data(self, region: str) -> ScheduleData:
        logger.info(f"[SCRAPER] fetch_schedule_data called for region={region}")

        if region in self._cache:
            logger.info(f"[SCRAPER] Cache hit for region {region}, returning cached data")
            return self._cache[region]

        logger.debug(f"[SCRAPER] Cache miss for region {region}, acquiring lock...")
        async with self._scraper_lock:
            logger.debug(f"[SCRAPER] Lock acquired for region {region}")

            if region in self._cache:
                logger.info(f"[SCRAPER] Cache populated while waiting for lock, returning cached data")
                return self._cache[region]

            logger.debug(f"[SCRAPER] Getting region configuration for {region}...")
            region_config = DTEK_REGIONS.get(region, DTEK_REGIONS["krem"])
            base_url = region_config["base_url"]
            logger.info(f"[SCRAPER] Region config: base_url={base_url}")

            logger.info(f"[SCRAPER] Fetching data with browser for region {region}...")
            try:
                html, cookie = await self._fetch_with_browser(base_url, headless=True, page_timeout=30000)
                logger.info(f"[SCRAPER] Browser fetch completed, parsing HTML...")
            except Exception as e:
                logger.exception(f"[SCRAPER] CRITICAL: Browser fetch failed for region {region}: {e}")
                raise

            try:
                schedule_data = self._parse_schedule_from_html(html, cookie)
                logger.info(f"[SCRAPER] HTML parsed successfully, caching data for region {region}")
            except Exception as e:
                logger.exception(f"[SCRAPER] CRITICAL: HTML parsing failed for region {region}: {e}")
                raise

            self._cache[region] = schedule_data
            logger.info(f"[SCRAPER] Schedule data cached for region {region}")

            return schedule_data

    async def _post_address_lookup(
        self,
        base_url: str,
        csrf_token: str,
        cookie: str,
        city: str,
        street: str,
        preset: Dict,
        skip_city: bool = False,
    ) -> Dict:
        logger.info(f"[SCRAPER] _post_address_lookup called: base_url={base_url}, city='{city}', street='{street}', skip_city={skip_city}")

        headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"{base_url}{SHUTDOWNS_PATH}",
            "Origin": base_url,
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": csrf_token,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Cookie": cookie,
        }

        if skip_city:
            payload = {
                "method": "getHomeNum",
                "data[0][name]": "street",
                "data[0][value]": street,
            }
            update_fact_index = 1
        else:
            payload = {
                "method": "getHomeNum",
                "data[0][name]": "city",
                "data[0][value]": city,
                "data[1][name]": "street",
                "data[1][value]": street,
            }
            update_fact_index = 2

        update_fact = preset.get("updateFact")
        if update_fact:
            payload[f"data[{update_fact_index}][name]"] = "updateFact"
            payload[f"data[{update_fact_index}][value]"] = str(update_fact)

        logger.debug(f"[SCRAPER] Prepared payload with {len(payload)} fields")

        session = None
        try:
            logger.debug(f"[SCRAPER] Creating aiohttp session...")
            async with aiohttp.ClientSession() as session:
                logger.debug(f"[SCRAPER] Session created, posting to {base_url}{AJAX_PATH}...")

                async with session.post(
                    f"{base_url}{AJAX_PATH}",
                    data=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    logger.info(f"[SCRAPER] HTTP POST completed, status={response.status}")

                    try:
                        response.raise_for_status()
                        logger.debug(f"[SCRAPER] Response status OK, parsing JSON...")
                    except aiohttp.ClientResponseError as e:
                        logger.error(f"[SCRAPER] HTTP error response: status={e.status}, message={e.message}")
                        raise

                    data = await response.json()
                    logger.info(f"[SCRAPER] Response parsed, result={data.get('result')}, has_data={bool(data.get('data'))}")

        except asyncio.TimeoutError as e:
            logger.exception(f"[SCRAPER] Address lookup timed out after 30 seconds")
            raise NetworkException("Address lookup timed out after 30 seconds.") from e
        except aiohttp.ClientError as e:
            logger.exception(f"[SCRAPER] Address lookup request failed: {type(e).__name__}: {e}")
            raise NetworkException(f"Address lookup request failed: {e}") from e
        except json.JSONDecodeError as e:
            logger.exception(f"[SCRAPER] Failed to parse address lookup response as JSON")
            raise ParsingException(f"Failed to parse address lookup response as JSON: {e}") from e
        except Exception as e:
            logger.exception(f"[SCRAPER] Unexpected error in address lookup: {type(e).__name__}: {e}")
            raise
        finally:
            if session and not session.closed:
                try:
                    logger.debug(f"[SCRAPER] Closing aiohttp session...")
                    await session.close()
                except Exception as e:
                    logger.warning(f"[SCRAPER] Error closing session: {e}")

        if not data.get("result"):
            error_msg = data.get("error", "Unknown error")
            logger.warning(f"[SCRAPER] Address lookup validation failed: {error_msg}")
            raise ValidationException(
                f"Address lookup failed: {error_msg}. "
                f"Please verify the city and street names are correct and in Ukrainian."
            )

        logger.info(f"[SCRAPER] Address lookup successful, returning data")
        return data["data"]

    async def lookup_queue(self, region: str, city: str, street: str, house: str) -> str:
        logger.info(f"[SCRAPER] lookup_queue called: region={region}, city='{city}', street='{street}', house='{house}'")

        if region not in self._cache:
            logger.debug(f"[SCRAPER] No cache for region {region}, fetching schedule data...")
            try:
                await self.fetch_schedule_data(region)
                logger.info(f"[SCRAPER] Schedule data fetched for region {region}")
            except Exception as e:
                logger.exception(f"[SCRAPER] CRITICAL: Failed to fetch schedule data for region {region}: {e}")
                raise

        cache = self._cache[region]
        logger.debug(f"[SCRAPER] Using cached data for region {region}")

        region_config = DTEK_REGIONS.get(region, DTEK_REGIONS["krem"])
        base_url = region_config["base_url"]
        skip_city = not region_config.get("has_city", True)

        if skip_city:
            lookup_city = ""
            lookup_street = street
        else:
            lookup_city = city
            lookup_street = street

        logger.info(f"[SCRAPER] Lookup params: region={region}, city='{lookup_city}', street='{lookup_street}', skip_city={skip_city}")

        try:
            logger.debug(f"[SCRAPER] Posting address lookup request...")
            house_data = await self._post_address_lookup(
                base_url,
                cache.csrf_token,
                cache.cookie,
                lookup_city,
                lookup_street,
                cache.preset,
                skip_city,
            )
            logger.info(f"[SCRAPER] Address lookup returned {len(house_data)} house entries")
        except Exception as e:
            logger.exception(f"[SCRAPER] CRITICAL: Address lookup failed: {e}")
            raise

        try:
            logger.debug(f"[SCRAPER] Picking queue from house data for house '{house}'...")
            queue = _pick_queue(house_data, house)
            logger.info(f"[SCRAPER] Queue resolved: {queue}")
            return queue
        except Exception as e:
            logger.exception(f"[SCRAPER] CRITICAL: Failed to pick queue for house '{house}': {e}")
            raise

    def get_status_for_date(
        self, fact: dict, queue: str, target_date: datetime
    ) -> Tuple[str, str, List[Tuple[str, str, str]], Optional[str], Optional[str], Dict[int, str]]:
        logger.debug(f"get_status_for_date called with queue={queue}, target_date={target_date.date()}")
        logger.debug(f"fact keys: {list(fact.keys())}")

        fact_data = fact.get("data", {})
        kyiv_tz = ZoneInfo("Europe/Kyiv")
        now = datetime.now(kyiv_tz)

        logger.debug(f"fact_data timestamps: {list(fact_data.keys())}")
        logger.debug(f"Looking for date: {target_date.date()}")

        day_data = None

        for ts, data in fact_data.items():
            try:
                ts_int = int(ts)
                dt = datetime.fromtimestamp(ts_int, tz=kyiv_tz)
                logger.debug(f"Checking timestamp {ts} -> date {dt.date()} (Kyiv)")
                if dt.date() == target_date.date():
                    day_data = data
                    logger.debug(f"Found target date data! Queues available: {list(data.keys())}")
                    break
            except (ValueError, OSError) as e:
                logger.debug(f"Failed to parse timestamp {ts}: {e}")
                continue

        if not day_data:
            logger.warning(f"No data found for target date ({target_date.date()})")
            return "unknown", "Невідомо", [], None, None, {}

        if queue not in day_data:
            logger.warning(f"Queue {queue} not found in day's data. Available queues: {list(day_data.keys())}")
            return "unknown", "Невідомо", [], None, None, {}

        periods = day_data[queue]
        logger.debug(f"Raw periods for queue {queue}: {periods}")

        hourly_schedule = {}
        for hour_str, status in periods.items():
            try:
                hour = int(hour_str)
                hourly_schedule[hour] = status
            except ValueError:
                continue

        logger.debug(f"Hourly schedule: {hourly_schedule}")

        schedule_blocks = _compress_day_detailed(periods)
        logger.debug(f"Compressed schedule blocks: {schedule_blocks}")

        check_time = now if target_date.date() == now.date() else target_date.replace(hour=0, minute=0)
        current_time_str = f"{check_time.hour:02d}:{check_time.minute:02d}"
        current_status = "unknown"

        for start, end, status in schedule_blocks:
            if start <= current_time_str < end:
                current_status = status
                break

        if target_date.date() != now.date() and schedule_blocks:
            current_status = schedule_blocks[0][2]

        next_change_time = None
        next_change_status = None

        for start, end, status in schedule_blocks:
            if start > current_time_str and status != current_status:
                next_change_time = start
                next_change_status = status
                break
            if start <= current_time_str < end:
                block_idx = schedule_blocks.index((start, end, status))
                if block_idx + 1 < len(schedule_blocks):
                    next_block = schedule_blocks[block_idx + 1]
                    if next_block[2] != status:
                        next_change_time = end
                        next_change_status = next_block[2]
                        break

        return current_status, STATUS_LABELS.get(current_status, "Невідомо"), schedule_blocks, next_change_time, next_change_status, hourly_schedule

    def get_current_status(
        self, fact: dict, queue: str
    ) -> Tuple[str, str, List[Tuple[str, str, str]], Optional[str], Optional[str], Dict[int, str]]:
        kyiv_tz = ZoneInfo("Europe/Kyiv")
        now = datetime.now(kyiv_tz)
        return self.get_status_for_date(fact, queue, now)

    def get_tomorrow_status(
        self, fact: dict, queue: str
    ) -> Tuple[str, str, List[Tuple[str, str, str]], Optional[str], Optional[str], Dict[int, str]]:
        from datetime import timedelta
        kyiv_tz = ZoneInfo("Europe/Kyiv")
        tomorrow = datetime.now(kyiv_tz) + timedelta(days=1)
        return self.get_status_for_date(fact, queue, tomorrow)
