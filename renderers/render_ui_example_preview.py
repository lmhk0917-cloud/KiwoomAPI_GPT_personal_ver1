import sqlite3
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app_paths import DATA_DIR, SCREENSHOT_DIR, ensure_app_dirs

DB = str(Path(DATA_DIR) / "example_run.db")
OUT = str(Path(SCREENSHOT_DIR) / "ui_dashboard_data_example.png")
FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_BOLD = r"C:\Windows\Fonts\malgunbd.ttf"


def font(size, bold=False):
    path = FONT_BOLD if bold and Path(FONT_BOLD).exists() else FONT
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def fetch_data():
    ensure_app_dirs()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    counts = {}
    for table in [
        "ticks",
        "analysis_results",
        "event_logs",
        "gpt_call_logs",
        "signal_logs",
        "notification_logs",
        "historical_bars",
    ]:
        counts[table] = conn.execute("select count(*) from " + table).fetchone()[0]

    latest = conn.execute("""
        select a.analyzed_at,a.code,a.name,a.current_price,a.rsi14,a.ma5,a.ma20,
               a.volume_ratio_20,a.vwap_distance_pct,a.box_position,
               (select group_concat(event_type, ', ')
                from event_logs e
                where e.code=a.code
                  and e.detected_at=(select max(detected_at) from event_logs where code=a.code)) as latest_events,
               (select action_hint
                from signal_logs s
                where s.code=a.code
                order by s.detected_at desc
                limit 1) as latest_signal
        from analysis_results a
        join (
            select code,max(id) latest_id
            from analysis_results
            group by code
        ) x on x.latest_id=a.id
        order by a.analyzed_at desc
    """).fetchall()

    events = conn.execute("""
        select detected_at,code,name,event_type,value,gpt_requested
        from event_logs
        order by id desc
        limit 7
    """).fetchall()

    signals = conn.execute("""
        select detected_at,code,name,action_hint,confidence_score,risk_level,
               current_price,stop_loss,target_1,target_2
        from signal_logs
        order by id desc
        limit 4
    """).fetchall()

    gpt = conn.execute("""
        select analyzed_at,code,name,current_price,substr(gpt_result,1,120) gpt
        from analysis_results
        order by id desc
        limit 1
    """).fetchone()
    conn.close()
    return counts, latest, events, signals, gpt


def draw_table(draw, title, x, y, w, h, headers, rows, col_widths, colors):
    text = colors["text"]
    border = colors["border"]
    white = colors["white"]
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=white, outline=border)
    draw.text((x + 14, y + 12), title, fill=text, font=font(15, True))
    ty = y + 42
    draw.rectangle([x + 12, ty, x + w - 12, ty + 30], fill="#eef2ff")
    cx = x + 14
    for head, cw in zip(headers, col_widths):
        draw.text((cx, ty + 7), head, fill="#374151", font=font(11, True))
        cx += cw

    row_y = ty + 34
    for idx, row in enumerate(rows):
        if row_y + 26 > y + h - 10:
            break
        if idx % 2 == 1:
            draw.rectangle([x + 12, row_y - 3, x + w - 12, row_y + 24], fill="#f9fafb")
        cx = x + 14
        for val, cw in zip(row, col_widths):
            value = "" if val is None else str(val)
            if len(value) > 36:
                value = value[:34] + ".."
            draw.text((cx, row_y + 2), value, fill=text, font=font(10))
            cx += cw
        row_y += 28


def main():
    counts, latest, events, signals, gpt = fetch_data()

    width, height = 1600, 930
    image = Image.new("RGB", (width, height), "#f4f6f8")
    draw = ImageDraw.Draw(image)
    colors = {
        "nav": "#17202a",
        "blue": "#2563eb",
        "border": "#d6dbe1",
        "text": "#1f2937",
        "muted": "#6b7280",
        "white": "#ffffff",
    }

    draw.rectangle([0, 0, width, 76], fill=colors["nav"])
    draw.text((24, 20), "Kiwoom OpenAI Personal Dashboard - Example Data", fill="white", font=font(24, True))
    draw.text((24, 50), "샘플 DB 기준 UI 출력 예시: Overview + GPT Result + Settings/Watchlist", fill="#cbd5e1", font=font(13))
    draw.rounded_rectangle([1330, 20, 1490, 52], radius=6, fill=colors["blue"])
    draw.text((1350, 27), "Auto Refresh ON", fill="white", font=font(13, True))

    x = 24
    for idx, tab in enumerate(["Overview", "GPT Result", "Analysis", "Events", "Signals", "Settings", "Watchlist"]):
        tab_width = draw.textlength(tab, font=font(13, True))
        fill = colors["blue"] if idx == 0 else "#e5e7eb"
        fg = "white" if idx == 0 else colors["text"]
        draw.rounded_rectangle([x, 92, x + tab_width + 34, 126], radius=6, fill=fill, outline=colors["border"])
        draw.text((x + 17, 101), tab, fill=fg, font=font(13, True))
        x += int(tab_width) + 44

    card_y = 146
    card_w = 204
    for idx, item in enumerate(counts.items()):
        key, value = item
        x = 24 + idx * (card_w + 14)
        if x + card_w > width - 24:
            break
        draw.rounded_rectangle([x, card_y, x + card_w, card_y + 78], radius=8, fill=colors["white"], outline=colors["border"])
        draw.text((x + 16, card_y + 15), key, fill=colors["muted"], font=font(12))
        draw.text((x + 16, card_y + 38), str(value), fill=colors["text"], font=font(24, True))

    latest_rows = []
    for row in latest:
        latest_rows.append([
            row["code"],
            row["name"],
            row["current_price"],
            row["rsi14"],
            row["volume_ratio_20"],
            row["vwap_distance_pct"],
            row["latest_signal"] or "-",
            row["latest_events"] or "-",
        ])

    draw_table(
        draw,
        "Latest Symbol Status",
        24,
        248,
        1552,
        190,
        ["Code", "Name", "Price", "RSI", "Vol20", "VWAP%", "Signal", "Latest Events"],
        latest_rows,
        [90, 130, 100, 80, 90, 90, 130, 760],
        colors,
    )

    event_rows = []
    for row in events:
        event_rows.append([
            row["detected_at"][11:19],
            row["code"],
            row["name"],
            row["event_type"],
            row["value"],
            "Y" if row["gpt_requested"] else "N",
        ])

    draw_table(
        draw,
        "Recent Events",
        24,
        462,
        760,
        230,
        ["Time", "Code", "Name", "Event", "Value", "GPT"],
        event_rows,
        [90, 80, 120, 270, 90, 60],
        colors,
    )

    signal_rows = []
    for row in signals:
        signal_rows.append([
            row["detected_at"][11:19],
            row["code"],
            row["action_hint"],
            row["confidence_score"],
            row["risk_level"],
            row["current_price"],
            row["stop_loss"],
            row["target_1"],
        ])

    draw_table(
        draw,
        "Recent Signals",
        816,
        462,
        760,
        230,
        ["Time", "Code", "Action", "Score", "Risk", "Price", "Stop", "T1"],
        signal_rows,
        [90, 80, 150, 70, 80, 90, 90, 90],
        colors,
    )

    draw.rounded_rectangle([24, 716, 1576, 900], radius=8, fill=colors["white"], outline=colors["border"])
    draw.text((44, 734), "GPT Result Preview", fill=colors["text"], font=font(15, True))
    if gpt:
        lines = [
            "{}  {}({})  price={}".format(gpt["analyzed_at"], gpt["name"], gpt["code"], gpt["current_price"]),
            "# 실시간 종목 분석",
            "## 간결 분석 요약",
            "- 현재 판단: 이벤트 발생 종목은 상세 분석으로 이동",
            "- 핵심 이벤트: 최근 이벤트 로그와 신호를 기준으로 표시",
            "## 이벤트 상세 분석",
            "- 매수 조건 / 손절 조건 / 익절 조건 / 반대 근거 / 체크리스트가 표시됩니다.",
        ]
    else:
        lines = ["No GPT result yet."]

    y = 766
    for line in lines:
        draw.text((44, y), line, fill=colors["text"], font=font(12 if not line.startswith("#") else 14, line.startswith("#")))
        y += 22

    draw.text((24, 910), "실제 UI에서는 각 탭에서 raw table, Settings, Watchlist를 직접 수정할 수 있습니다.", fill=colors["muted"], font=font(11))
    image.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
