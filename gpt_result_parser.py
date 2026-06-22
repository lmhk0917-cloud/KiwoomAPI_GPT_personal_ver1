"""Parse structured GPT trading analysis output.

The GPT prompt asks for strict JSON, but live LLM output can still contain
markdown fences or commentary. This parser is deliberately defensive: it
extracts the first JSON object it can find and returns per-code score rows.
Raw GPT text remains stored separately in analysis_results.
"""

import json
import re
from datetime import datetime


SCORE_FIELDS = (
    "risk_score",
    "gpt_context_score",
    "breakout_score",
    "trend_score",
    "confidence",
)


def parse_gpt_analysis_scores(result_text, summaries, gpt_call_id=None, analyzed_at=None):
    """Return rows suitable for gpt_analysis_scores."""
    analyzed_at = analyzed_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    codes = [summary.get("code") for summary in summaries or [] if summary.get("code")]
    parsed, error = extract_json_object(result_text)
    symbols = _symbols_by_code(parsed) if isinstance(parsed, dict) else {}

    rows = []
    for code in codes:
        item = symbols.get(code)
        if item:
            rows.append(_score_row(
                code=code,
                item=item,
                gpt_call_id=gpt_call_id,
                analyzed_at=analyzed_at,
                parse_status="parsed",
                error_message=None,
            ))
        else:
            rows.append(_empty_row(
                code=code,
                gpt_call_id=gpt_call_id,
                analyzed_at=analyzed_at,
                parse_status="missing_symbol" if parsed else "parse_failed",
                error_message=error,
            ))
    return rows


def extract_json_object(text):
    """Extract and decode a JSON object from free-form model text."""
    if not text:
        return None, "empty_result"

    cleaned = _strip_code_fence(str(text).strip())
    candidates = [cleaned]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", str(text), flags=re.DOTALL | re.IGNORECASE)
    candidates = fenced + candidates

    brace_candidate = _first_balanced_object(str(text))
    if brace_candidate:
        candidates.append(brace_candidate)

    last_error = None
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError as exc:
            last_error = str(exc)
            continue
        if isinstance(value, dict):
            return value, None
    return None, last_error or "json_object_not_found"


def _strip_code_fence(text):
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _first_balanced_object(text):
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _symbols_by_code(parsed):
    symbols = parsed.get("symbols") if isinstance(parsed, dict) else None
    if not isinstance(symbols, list):
        return {}
    result = {}
    for item in symbols:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if code:
            result[code] = item
    return result


def _score_row(code, item, gpt_call_id, analyzed_at, parse_status, error_message):
    return {
        "gpt_call_id": gpt_call_id,
        "analyzed_at": analyzed_at,
        "code": code,
        "parse_status": parse_status,
        "decision": _text(item.get("decision")),
        "risk_score": _number(item.get("risk_score")),
        "gpt_context_score": _number(item.get("gpt_context_score")),
        "breakout_score": _number(item.get("breakout_score")),
        "trend_score": _number(item.get("trend_score")),
        "confidence": _number(item.get("confidence")),
        "risk_flags": item.get("risk_flags") if isinstance(item.get("risk_flags"), list) else [],
        "invalid_condition": _text(item.get("invalid_condition")),
        "summary": _text(item.get("summary")),
        "entry_plan": _text(item.get("entry_plan")),
        "raw_json": item,
        "error_message": error_message,
    }


def _empty_row(code, gpt_call_id, analyzed_at, parse_status, error_message):
    return {
        "gpt_call_id": gpt_call_id,
        "analyzed_at": analyzed_at,
        "code": code,
        "parse_status": parse_status,
        "decision": None,
        "risk_score": None,
        "gpt_context_score": None,
        "breakout_score": None,
        "trend_score": None,
        "confidence": None,
        "risk_flags": [],
        "invalid_condition": None,
        "summary": None,
        "entry_plan": None,
        "raw_json": None,
        "error_message": error_message,
    }


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value):
    if value is None:
        return None
    return str(value)
