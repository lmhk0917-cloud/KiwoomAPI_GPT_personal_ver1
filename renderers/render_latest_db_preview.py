"""Render a dashboard-like preview from the real SQLite DB.

This is safer than opening the live PyQt dashboard when the user only wants to
review stored data. It uses the latest persisted rows from ``data/ticks.db``.
"""

import sqlite3
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app_paths import DEFAULT_DB_PATH, SCREENSHOT_DIR, ensure_app_dirs


OUT = str(Path(SCREENSHOT_DIR) / "latest_db_analysis_preview.png")
FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_BOLD = r"C:\Windows\Fonts\malgunbd.ttf"


def font(size, bold=False):
    path = FONT_BOLD if bold and Path(FONT_BOLD).exists() else FONT
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def main():
    ensure_app_dirs()
    data = fetch_data()
    render(data)
    print("PREVIEW_IMAGE={}".format(OUT))


def fetch_data():
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        counts = {}
        for table in [
            "ticks",
            "analysis_results",
            "event_logs",
            "gpt_call_logs",
            "signal_logs",
            "notification_logs",
        ]:
            counts[table] = conn.execute("select count(*) from " + table).fetchone()[0]

        latest_tick = conn.execute("""
            select code, max(received_at) latest_received_at, count(*) tick_count
            from ticks
            group by code
            order by latest_received_at desc
            limit 8
        """).fetchall()

        latest_analysis = conn.execute("""
            select id, analyzed_at, code, name, current_price, rsi14, ma5, ma20,
                   volume_ratio_20, vwap_distance_pct, box_position, gpt_result
            from analysis_results
            order by id desc
            limit 1
        """).fetchone()

        recent_events = conn.execute("""
            select detected_at, code, name, event_type, timeframe, value, gpt_requested
            from event_logs
            order by id desc
            limit 8
        """).fetchall()

        recent_signals = conn.execute("""
            select detected_at, code, name, action_hint, confidence_score, risk_level,
                   current_price, stop_loss, target_1, target_2
            from signal_logs
            order by id desc
            limit 5
        """).fetchall()

        latest_gpt_call = conn.execute("""
            select started_at, status, model, duration_ms, prompt_tokens,
                   completion_tokens, total_tokens, codes
            from gpt_call_logs
            order by id desc
            limit 1
        """).fetchone()

        return {
            "counts": counts,
            "latest_tick": latest_tick,
            "latest_analysis": latest_analysis,
            "recent_events": recent_events,
            "recent_signals": recent_signals,
            "latest_gpt_call": latest_gpt_call,
        }
    finally:
        conn.close()


def render(data):
    width, height = 1600, 980
    image = Image.new("RGB", (width, height), "#f4f6f8")
    draw = ImageDraw.Draw(image)

    colors = {
        "nav": "#17202a",
        "blue": "#2563eb",
        "border": "#d6dbe1",
        "text": "#1f2937",
        "muted": "#6b7280",
        "white": "#ffffff",
        "panel": "#eef2ff",
    }

    draw.rectangle([0, 0, width, 80], fill=colors["nav"])
    draw.text((24, 18), "Kiwoom OpenAI Personal Dashboard - Stored Data Preview", fill="white", font=font(24, True))
    draw.text((24, 50), "실제 SQLite DB 기준: 최근 온라인 테스트 데이터 + GPT 재호출 로그", fill="#cbd5e1", font=font(13))

    x = 24
    for key, value in data["counts"].items():
        draw_card(draw, x, 104, 238, 76, key, value, colors)
        x += 252
        if x > 1320:
            break

    latest = data["latest_analysis"]
    if latest:
        draw_card(draw, 24, 204, 360, 112, "Latest Analysis", "{} / {} / {}".format(
            latest["id"], latest["code"], latest["name"]
        ), colors, subtitle=latest["analyzed_at"])
        draw_card(draw, 408, 204, 220, 112, "Price", latest["current_price"], colors)
        draw_card(draw, 652, 204, 220, 112, "RSI14", latest["rsi14"], colors)
        draw_card(draw, 896, 204, 220, 112, "Vol Ratio 20", latest["volume_ratio_20"], colors)
        draw_card(draw, 1140, 204, 220, 112, "VWAP Dist %", latest["vwap_distance_pct"], colors)

    draw_table(
        draw,
        "Latest Tick State",
        24,
        344,
        520,
        210,
        ["Code", "Latest", "Ticks"],
        [[r["code"], r["latest_received_at"], r["tick_count"]] for r in data["latest_tick"]],
        [90, 280, 110],
        colors,
    )

    draw_table(
        draw,
        "Recent Events",
        568,
        344,
        1008,
        210,
        ["Time", "Code", "Name", "Event", "TF", "Value", "GPT"],
        [[
            short_time(r["detected_at"]),
            r["code"],
            r["name"],
            r["event_type"],
            r["timeframe"],
            r["value"],
            "Y" if r["gpt_requested"] else "N",
        ] for r in data["recent_events"]],
        [90, 80, 120, 300, 70, 100, 50],
        colors,
    )

    draw_table(
        draw,
        "Recent Signals",
        24,
        584,
        760,
        220,
        ["Time", "Code", "Action", "Score", "Risk", "Price", "Stop", "Target"],
        [[
            short_time(r["detected_at"]),
            r["code"],
            r["action_hint"],
            r["confidence_score"],
            r["risk_level"],
            r["current_price"],
            r["stop_loss"],
            r["target_1"],
        ] for r in data["recent_signals"]],
        [85, 80, 150, 70, 70, 95, 95, 95],
        colors,
    )

    call = data["latest_gpt_call"]
    call_text = "없음"
    if call:
        call_text = (
            "started={} | status={} | model={} | duration={}ms | tokens={}/{} total={}"
        ).format(
            call["started_at"],
            call["status"],
            call["model"],
            call["duration_ms"],
            call["prompt_tokens"],
            call["completion_tokens"],
            call["total_tokens"],
        )
    draw_text_panel(draw, 816, 584, 760, 90, "Latest GPT Call", call_text, colors)

    gpt_result = latest["gpt_result"] if latest else ""
    draw_text_panel(draw, 816, 692, 760, 248, "Latest GPT Result", gpt_result, colors, wrap=56, max_lines=10)

    Path(OUT).parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT)


def draw_card(draw, x, y, w, h, title, value, colors, subtitle=None):
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=colors["white"], outline=colors["border"])
    draw.text((x + 14, y + 14), str(title), fill=colors["muted"], font=font(12))
    draw.text((x + 14, y + 38), str(value), fill=colors["text"], font=font(20, True))
    if subtitle:
        draw.text((x + 14, y + h - 24), str(subtitle), fill=colors["muted"], font=font(11))


def draw_table(draw, title, x, y, w, h, headers, rows, col_widths, colors):
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=colors["white"], outline=colors["border"])
    draw.text((x + 14, y + 12), title, fill=colors["text"], font=font(15, True))
    ty = y + 42
    draw.rectangle([x + 12, ty, x + w - 12, ty + 30], fill=colors["panel"])
    cx = x + 14
    for head, cw in zip(headers, col_widths):
        draw.text((cx, ty + 7), str(head), fill="#374151", font=font(11, True))
        cx += cw

    row_y = ty + 36
    for idx, row in enumerate(rows):
        if row_y + 26 > y + h - 10:
            break
        if idx % 2 == 1:
            draw.rectangle([x + 12, row_y - 3, x + w - 12, row_y + 24], fill="#f9fafb")
        cx = x + 14
        for val, cw in zip(row, col_widths):
            value = "" if val is None else str(val)
            if len(value) > 34:
                value = value[:32] + ".."
            draw.text((cx, row_y + 2), value, fill=colors["text"], font=font(10))
            cx += cw
        row_y += 28


def draw_text_panel(draw, x, y, w, h, title, body, colors, wrap=88, max_lines=4):
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=colors["white"], outline=colors["border"])
    draw.text((x + 14, y + 12), title, fill=colors["text"], font=font(15, True))
    lines = []
    for raw_line in str(body or "").splitlines():
        lines.extend(textwrap.wrap(raw_line, width=wrap) or [""])
    for idx, line in enumerate(lines[:max_lines]):
        draw.text((x + 14, y + 44 + idx * 22), line, fill=colors["text"], font=font(11))


def short_time(value):
    if not value:
        return ""
    text = str(value)
    if len(text) >= 19:
        return text[11:19]
    return text


if __name__ == "__main__":
    main()
