"""Best-effort macro context crawler.

This module intentionally uses only Python standard-library tools so it works
inside the 32-bit Kiwoom conda environment. Crawled values are supplemental
context for GPT, not a trading feed. Failures are returned as notes instead of
raising so the realtime app can continue during market hours.
"""

import argparse
import html
import json
import re
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

import config


USER_AGENT = "Mozilla/5.0 KiwoomGPTPersonal/1.0"


class TextExtractor(HTMLParser):
    """Extract readable text from HTML while ignoring scripts/styles."""

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "noscript"):
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style", "noscript") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = " ".join((data or "").split())
        if text:
            self.parts.append(text)

    def text(self):
        return " ".join(self.parts)


def fetch_macro_context(settings=None):
    """Return a macro_context dict suitable for MarketContextStore."""
    settings = settings or {}
    timeout = _setting(settings, "MACRO_CONTEXT_TIMEOUT_SEC", config.MACRO_CONTEXT_TIMEOUT_SEC)
    base_rate_url = _setting(settings, "MACRO_BOK_BASE_RATE_URL", config.MACRO_BOK_BASE_RATE_URL)
    fed_url = _setting(settings, "MACRO_FED_OPEN_MARKET_URL", config.MACRO_FED_OPEN_MARKET_URL)
    calendar_urls = _setting(settings, "MACRO_EVENT_CALENDAR_URLS", config.MACRO_EVENT_CALENDAR_URLS)

    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = config.MACRO_CONTEXT_TIMEOUT_SEC

    result = {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "source": "crawler",
        "reliability": "crawler_unverified",
        "summary": None,
        "risk_regime": None,
        "risk_regime_reason": None,
        "kr_base_rate": None,
        "kr_base_rate_change_bp": None,
        "us_fed_funds_rate": None,
        "us_fed_funds_target_lower": None,
        "us_fed_funds_target_upper": None,
        "next_macro_events": [],
        "notes": [],
    }

    base_rate = fetch_bok_base_rate(base_rate_url, timeout)
    if base_rate.get("kr_base_rate") is not None:
        result["kr_base_rate"] = base_rate["kr_base_rate"]
    if base_rate.get("summary"):
        result["summary"] = base_rate["summary"]
    result["notes"].extend(base_rate.get("notes") or [])

    fed_rate = fetch_fed_funds_target_range(fed_url, timeout)
    for key in (
        "us_fed_funds_rate",
        "us_fed_funds_target_lower",
        "us_fed_funds_target_upper",
    ):
        if fed_rate.get(key) is not None:
            result[key] = fed_rate[key]
    result["notes"].extend(fed_rate.get("notes") or [])

    events = []
    for url in calendar_urls or []:
        calendar_result = fetch_event_calendar(url, timeout)
        events.extend(calendar_result.get("events") or [])
        result["notes"].extend(calendar_result.get("notes") or [])

    result["next_macro_events"] = events[:8]
    summary_parts = []
    if result["kr_base_rate"] is not None:
        summary_parts.append("한국은행 기준금리 {}%".format(result["kr_base_rate"]))
    if result["us_fed_funds_rate"] is not None:
        summary_parts.append("미국 연방기금 목표금리 중간값 {}%".format(result["us_fed_funds_rate"]))
    if summary_parts:
        result["summary"] = " / ".join(summary_parts)

    if (
        result["kr_base_rate"] is None
        and result["us_fed_funds_rate"] is None
        and not result["next_macro_events"]
    ):
        result["reliability"] = "crawler_failed_or_empty"

    return _drop_empty(result)


def fetch_bok_base_rate(url, timeout):
    """Crawl the Bank of Korea base-rate page and extract a best-effort rate."""
    output = {"kr_base_rate": None, "summary": None, "notes": []}

    try:
        html_text = _fetch_html(url, timeout)
        text = _html_to_text(html_text)
    except Exception as exc:
        output["notes"].append("BOK base-rate crawl failed: {}".format(exc))
        return output

    rate = _extract_base_rate(html_text)
    if rate is None:
        output["notes"].append("BOK base-rate value not found in page text.")
        return output

    output["kr_base_rate"] = rate
    output["summary"] = "한국은행 기준금리 {}%".format(rate)
    output["notes"].append("BOK base-rate source: {}".format(url))
    return output


def fetch_fed_funds_target_range(url, timeout):
    """Crawl Federal Reserve target fed funds range from an official page."""
    output = {
        "us_fed_funds_rate": None,
        "us_fed_funds_target_lower": None,
        "us_fed_funds_target_upper": None,
        "notes": [],
    }

    try:
        text = _fetch_text(url, timeout)
    except Exception as exc:
        output["notes"].append("Fed funds target crawl failed: {}".format(exc))
        return output

    target_range = _extract_fed_target_range(text)
    if not target_range:
        output["notes"].append("Fed funds target range not found in page text.")
        return output

    lower, upper = target_range
    output["us_fed_funds_target_lower"] = lower
    output["us_fed_funds_target_upper"] = upper
    output["us_fed_funds_rate"] = round((lower + upper) / 2.0, 4)
    output["notes"].append("Fed funds target source: {}".format(url))
    return output


def fetch_event_calendar(url, timeout):
    """Extract upcoming macro/policy events from a public calendar page."""
    output = {"events": [], "notes": []}

    try:
        text = _fetch_text(url, timeout)
    except Exception as exc:
        output["notes"].append("Macro calendar crawl failed: {} ({})".format(url, exc))
        return output

    events = _extract_calendar_events(text, source=url)
    if not events:
        output["notes"].append("No macro calendar events parsed from: {}".format(url))
    output["events"] = events
    return output


def _fetch_text(url, timeout):
    return _html_to_text(_fetch_html(url, timeout))


def _fetch_html(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"

    try:
        html_text = raw.decode(charset, errors="replace")
    except LookupError:
        html_text = raw.decode("utf-8", errors="replace")

    return html_text


def _html_to_text(html_text):
    parser = TextExtractor()
    parser.feed(html_text)
    return html.unescape(parser.text())


def _extract_base_rate(text):
    normalized = " ".join((text or "").split())

    chart_match = re.search(r"chartObj2_s\s*=\s*\[(.*?)\]\s*/\*", text or "", re.S)
    if not chart_match:
        chart_match = re.search(r"chartObj2_s\s*=\s*\[(.*?)\]\s*var\s+chartObj2Labels", text or "", re.S)
    if chart_match:
        pairs = re.findall(r"\[\s*\"([0-9/:\s]+)\"\s*,\s*([0-9.]+)\s*\]", chart_match.group(1))
        plausible_pairs = [
            (date_text.strip(), float(rate_text))
            for date_text, rate_text in pairs
            if _is_plausible_policy_rate(float(rate_text))
        ]
        if plausible_pairs:
            return plausible_pairs[-1][1]

    candidates = []
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*%", normalized):
        rate = float(match.group(1))
        if not _is_plausible_policy_rate(rate):
            continue
        start = max(match.start() - 80, 0)
        end = min(match.end() + 80, len(normalized))
        window = normalized[start:end]
        if "기준금리" in window or "base rate" in window.lower():
            candidates.append(rate)

    if candidates:
        return candidates[-1]

    for generic in re.finditer(r"기준금리[^0-9]{0,80}(\d+(?:\.\d+)?)", normalized):
        rate = float(generic.group(1))
        if _is_plausible_policy_rate(rate):
            candidates.append(rate)

    if candidates:
        return candidates[-1]

    return None


def _extract_fed_target_range(text):
    normalized = " ".join(
        (text or "")
        .replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .split()
    )
    ranges = []

    table_match = re.search(
        r"FOMC's target federal funds rate or range.*?Level \(%\)\s+([A-Za-z]+\s+\d{1,2})\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)",
        normalized,
        re.I,
    )
    if table_match:
        lower = float(table_match.group(2))
        upper = float(table_match.group(3))
        if _is_plausible_policy_rate(lower) and _is_plausible_policy_rate(upper):
            return (min(lower, upper), max(lower, upper))

    for match in re.finditer(
        r"(\d+(?:\.\d+)?)\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*(?:percent|%)?",
        normalized,
        re.I,
    ):
        lower = float(match.group(1))
        upper = float(match.group(2))
        if not (_is_plausible_policy_rate(lower) and _is_plausible_policy_rate(upper)):
            continue
        if lower > upper:
            lower, upper = upper, lower

        start = max(match.start() - 160, 0)
        end = min(match.end() + 160, len(normalized))
        window = normalized[start:end].lower()
        if "federal funds" in window or "fomc" in window or "target range" in window:
            ranges.append((lower, upper))

    if ranges:
        return ranges[0]

    return None


def _is_plausible_policy_rate(value):
    return 0.0 <= float(value) <= 20.0


def _extract_calendar_events(text, source):
    normalized = " ".join((text or "").split())
    now = datetime.now()
    current_year = now.year
    year_match = re.search(r"(20\d{2})년\s+년도선택", normalized)
    if year_match:
        current_year = int(year_match.group(1))
    events = []

    if "통화정책방향 회의" in normalized or "통화정책방향 결정회의" in normalized:
        for match in re.finditer(r"(\d{1,2})월\s*(\d{1,2})일", normalized):
            try:
                event_dt = datetime(current_year, int(match.group(1)), int(match.group(2)))
            except ValueError:
                continue
            if event_dt.date() < now.date():
                continue
            events.append({
                "date": event_dt.strftime("%Y-%m-%d"),
                "title": "한국은행 통화정책방향 결정회의",
                "source": source,
                "category": "monetary_policy",
                "weight": "high",
            })
            if len(events) >= 8:
                return events

    patterns = [
        r"((?:20\d{2})[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2})[^0-9]{0,80}(통화정책방향[^.。]{0,80}|금융통화위원회[^.。]{0,80}|기준금리[^.。]{0,80})",
        r"(\d{1,2}[.\-/월]\s*\d{1,2})[^0-9]{0,80}(통화정책방향[^.。]{0,80}|금융통화위원회[^.。]{0,80}|기준금리[^.。]{0,80})",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            event_date = _normalize_date(match.group(1), current_year)
            title = " ".join(match.group(2).split())
            item = {
                "date": event_date,
                "title": title[:120],
                "source": source,
                "category": "monetary_policy",
                "weight": "medium",
            }
            if item not in events:
                events.append(item)
            if len(events) >= 8:
                return events

    return events


def _normalize_date(value, default_year):
    value = (value or "").replace("년", ".").replace("월", ".").replace("일", "")
    value = value.replace("/", ".").replace("-", ".")
    parts = [part.strip() for part in value.split(".") if part.strip()]

    if len(parts) == 2:
        year = default_year
        month, day = parts
    elif len(parts) >= 3:
        year, month, day = parts[:3]
    else:
        return value

    try:
        return "{:04d}-{:02d}-{:02d}".format(int(year), int(month), int(day))
    except ValueError:
        return value


def _setting(settings, key, default):
    return (settings or {}).get(key, default)


def _drop_empty(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if item is None or item == "" or item == [] or item == {}:
                continue
            result[key] = item
        return result
    return value


def main():
    parser = argparse.ArgumentParser(description="Fetch macro context for GPT input.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    context = fetch_macro_context()
    if args.json:
        print(json.dumps(context, ensure_ascii=False, indent=2))
    else:
        print("MACRO_CONTEXT={}".format(json.dumps(context, ensure_ascii=False)))


if __name__ == "__main__":
    main()
