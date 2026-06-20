"""Toss-style read-only dashboard for the Kiwoom personal runtime."""

import argparse
import html
import json
import os
import sqlite3
import sys
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import ttk

from app_paths import DEFAULT_DB_PATH, EXPORTS_DIR


DEFAULT_SYMBOLS = ["005930", "000660"]
DEFAULT_HTML_PATH = os.path.join(EXPORTS_DIR, "kiwoom_dashboard_latest.html")
DEFAULT_SYMBOLS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "watchlists",
    "domestic_kr.json",
)


def build_dashboard_snapshot(db_path=DEFAULT_DB_PATH, symbols=None):
    symbols = [str(item).strip() for item in symbols or [] if str(item).strip()]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if not symbols:
            symbols = _symbols_from_db(conn)
        if not symbols:
            symbols = list(DEFAULT_SYMBOLS)

        tables = _table_counts(conn)
        latest = _latest_times(conn)
        health = _health(latest)
        rows = []
        for code in symbols:
            tick = _latest_tick(conn, code)
            signal = _latest_signal(conn, code)
            analysis = _latest_analysis(conn, code)
            paper = _paper_summary(conn, code)
            rows.append({
                "code": code,
                "name": signal.get("name") or analysis.get("name") or "",
                "price": tick.get("price") or signal.get("current_price") or analysis.get("current_price"),
                "change_rate": tick.get("change_rate"),
                "volume_ratio": tick.get("tick_volume"),
                "tick_time": tick.get("received_at"),
                "action": signal.get("action_hint") or "none",
                "score": signal.get("confidence_score"),
                "risk": signal.get("risk_level") or "unknown",
                "confidence": "db",
                "analysis_time": analysis.get("analyzed_at"),
                "gpt_result": analysis.get("gpt_result") or "",
                "summary_json": analysis.get("summary_json") or "",
                "market_context_json": analysis.get("market_context_json") or "",
                "paper": paper,
                "events": _recent_events(conn, code=code, limit=16),
                "signals": _recent_signals(conn, code=code, limit=16),
                "paper_rows": _recent_paper(conn, code=code, limit=16),
                "contexts": _recent_contexts(conn, code=code, limit=12),
                "tick_series": _recent_ticks(conn, code=code, limit=120),
                "score_history": _recent_signal_scores(conn, code=code, limit=12),
            })

        return {
            "generated_at": _now(),
            "db_path": os.path.abspath(db_path),
            "symbols": symbols,
            "tables": tables,
            "latest": latest,
            "health": health,
            "rows": rows,
            "recent_events": _recent_events(conn, limit=30),
            "recent_signals": _recent_signals(conn, limit=30),
            "recent_paper": _recent_paper(conn, limit=30),
            "recent_contexts": _recent_contexts(conn, limit=30),
            "latest_gpt_call": _latest_gpt_call(conn),
        }
    finally:
        conn.close()


def render_dashboard_html(snapshot):
    rows_html = "\n".join(_symbol_html(row) for row in snapshot.get("rows") or [])
    events_html = "\n".join(_event_html(row) for row in snapshot.get("recent_events") or [])
    context_html = "\n".join(_context_html(row) for row in snapshot.get("recent_contexts") or [])
    paper_html = "\n".join(_paper_html(row) for row in snapshot.get("recent_paper") or [])
    table_html = "\n".join(
        "<tr><td>{}</td><td class=\"num\">{}</td></tr>".format(_e(key), _e(value))
        for key, value in sorted((snapshot.get("tables") or {}).items())
    )
    health = snapshot.get("health") or {}
    latest = snapshot.get("latest") or {}
    warnings = health.get("warnings") or []
    warning_text = ", ".join(warnings) if warnings else "none"
    status_class = "status-ok" if health.get("status") == "ok" else "status-warn"
    return """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kiwoom Focused Dashboard</title>
<style>
:root {{ --bg:#f6f7f9; --panel:#fff; --line:#d9dee7; --text:#1d2430; --muted:#667085; --blue:#1b64d8; --green:#147a42; --red:#b42318; --amber:#b54708; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font-family:Segoe UI, Arial, sans-serif; letter-spacing:0; }}
header {{ padding:18px 24px 14px; background:var(--panel); border-bottom:1px solid var(--line); }}
h1 {{ margin:0 0 6px; font-size:22px; font-weight:650; }}
h2 {{ margin:0 0 10px; font-size:16px; font-weight:650; }}
.meta {{ color:var(--muted); font-size:13px; }}
main {{ padding:18px 24px 28px; display:grid; gap:16px; }}
section {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }}
.metrics {{ display:grid; grid-template-columns:repeat(4,minmax(140px,1fr)); gap:10px; }}
.metric {{ border-left:4px solid var(--blue); background:#fbfcfe; padding:10px 12px; min-height:68px; }}
.metric .label {{ color:var(--muted); font-size:12px; }}
.metric .value {{ margin-top:5px; font-size:20px; font-weight:650; overflow-wrap:anywhere; }}
.status-ok {{ color:var(--green); font-weight:650; }}
.status-warn {{ color:var(--amber); font-weight:650; }}
table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
th,td {{ padding:9px 8px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; font-size:13px; overflow-wrap:anywhere; }}
th {{ color:#344054; font-size:12px; background:#f9fafb; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.pos {{ color:var(--green); font-weight:600; }}
.neg {{ color:var(--red); font-weight:600; }}
.muted {{ color:var(--muted); }}
.pill {{ display:inline-block; min-width:58px; padding:3px 7px; border-radius:999px; background:#eef4ff; color:#1849a9; text-align:center; font-size:12px; font-weight:650; }}
.risk-HIGH {{ background:#fef3f2; color:var(--red); }}
.risk-MEDIUM {{ background:#fffaeb; color:var(--amber); }}
.risk-LOW {{ background:#ecfdf3; color:var(--green); }}
.summary {{ color:var(--muted); line-height:1.4; max-height:76px; overflow:hidden; }}
@media (max-width:900px) {{
  header, main {{ padding-left:12px; padding-right:12px; }}
  .metrics {{ grid-template-columns:repeat(2,minmax(120px,1fr)); }}
  table {{ table-layout:auto; }}
  th,td {{ font-size:12px; }}
}}
</style>
</head>
<body>
<header>
  <h1>Kiwoom Focused Dashboard</h1>
  <div class="meta">Generated {generated_at} | DB {db_path}</div>
</header>
<main>
  <section>
    <h2>Runtime</h2>
    <div class="metrics">
      <div class="metric"><div class="label">Health</div><div class="value {status_class}">{status}</div></div>
      <div class="metric"><div class="label">Latest Analysis</div><div class="value">{latest_analysis}</div></div>
      <div class="metric"><div class="label">Tokens</div><div class="value">{latest_tokens}</div></div>
      <div class="metric"><div class="label">Warnings</div><div class="value">{warning_count}</div></div>
    </div>
    <p class="meta">Warnings: {warning_text}</p>
  </section>
  <section>
    <h2>Domestic KR</h2>
    <table>
      <thead><tr><th>Symbol</th><th>Decision</th><th class="num">Score</th><th class="num">Delta</th><th class="num">Avg Ret</th><th class="num">Win</th><th class="num">Worst Path</th><th>Risk</th><th>Confidence</th><th class="num">Price</th><th class="num">1m %</th><th class="num">1m Vol</th><th class="num">1d %</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </section>
  <section><h2>Events By Symbol</h2><table><thead><tr><th>Time</th><th>Symbol</th><th>Event</th><th>Severity</th><th class="num">Value</th><th>Message</th></tr></thead><tbody>{events_html}</tbody></table></section>
  <section><h2>Paper Feedback</h2><table><thead><tr><th>Created</th><th>Symbol</th><th class="num">Horizon</th><th class="num">Anchor</th><th>Status</th><th class="num">Return</th><th class="num">Max</th><th class="num">Min</th><th>Outcome</th></tr></thead><tbody>{paper_html}</tbody></table></section>
  <section><h2>Context</h2><table><thead><tr><th>Time</th><th>Scope</th><th>Symbol</th><th>Section</th><th>Reliability</th><th>Summary</th></tr></thead><tbody>{context_html}</tbody></table></section>
  <section><h2>Tables</h2><table><tbody>{table_html}</tbody></table></section>
</main>
</body>
</html>""".format(
        generated_at=_e(snapshot.get("generated_at")),
        db_path=_e(snapshot.get("db_path")),
        status_class=status_class,
        status=_e(health.get("status") or "unknown"),
        latest_analysis=_e(latest.get("analysis_results") or "none"),
        latest_tokens=_e((snapshot.get("latest_gpt_call") or {}).get("total_tokens") or 0),
        warning_count=_e(len(warnings)),
        warning_text=_e(warning_text),
        rows_html=rows_html,
        events_html=events_html,
        paper_html=paper_html,
        context_html=context_html,
        table_html=table_html,
    )


class KiwoomFocusedDashboard(object):
    def __init__(self, root, symbols, db_path=DEFAULT_DB_PATH, refresh_sec=30, symbols_path=DEFAULT_SYMBOLS_PATH):
        self.root = root
        self.symbols = symbols or list(DEFAULT_SYMBOLS)
        self.db_path = db_path
        self.symbols_path = symbols_path
        self.refresh_ms = max(5, int(refresh_sec)) * 1000
        self.snapshot = {}
        self.root.title("Kiwoom Focused Dashboard")
        self.root.geometry("1280x820+80+60")
        self.root.minsize(980, 640)
        self._show_in_foreground()
        self._build_ui()
        self.refresh()

    def _show_in_foreground(self):
        self.root.update_idletasks()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.root.attributes("-topmost", True)
        self.root.after(1200, lambda: self.root.attributes("-topmost", False))

    def _build_ui(self):
        self.root.configure(bg="#f6f7f9")
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), background="#ffffff", foreground="#1d2430")
        style.configure("Meta.TLabel", font=("Segoe UI", 9), background="#ffffff", foreground="#667085")
        style.configure("Metric.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("MetricLabel.TLabel", font=("Segoe UI", 9), background="#ffffff", foreground="#667085")
        style.configure("MetricValue.TLabel", font=("Segoe UI", 14, "bold"), background="#ffffff", foreground="#1d2430")

        header = ttk.Frame(self.root, padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Kiwoom Focused Dashboard", style="Header.TLabel").pack(anchor="w")
        self.meta_var = tk.StringVar(value="Loading...")
        ttk.Label(header, textvariable=self.meta_var, style="Meta.TLabel").pack(anchor="w", pady=(3, 0))

        toolbar = ttk.Frame(self.root, padding=(16, 8))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(toolbar, text="Export HTML", command=self.export_html).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Open HTML", command=self.open_html).pack(side="left", padx=(4, 0))
        ttk.Label(toolbar, text="Symbols").pack(side="left", padx=(12, 4))
        self.symbols_var = tk.StringVar(value=",".join(self.symbols))
        ttk.Entry(toolbar, textvariable=self.symbols_var, width=34).pack(side="left")
        ttk.Button(toolbar, text="Apply", command=self.apply_symbols).pack(side="left", padx=(4, 0))
        ttk.Button(toolbar, text="Reload", command=self.reload_symbols).pack(side="left", padx=(4, 0))
        ttk.Button(toolbar, text="Quit", command=self.root.destroy).pack(side="right")
        self.status_var = tk.StringVar(value="")
        ttk.Label(toolbar, textvariable=self.status_var).pack(side="left", padx=(12, 0))

        metric_bar = ttk.Frame(self.root, padding=(16, 4))
        metric_bar.pack(fill="x")
        self.metric_vars = {}
        for key, label in [
            ("health", "Health"),
            ("latest_analysis", "Latest Analysis"),
            ("tokens", "Tokens"),
            ("warnings", "Warnings"),
        ]:
            frame = ttk.Frame(metric_bar, style="Metric.TFrame", padding=(12, 10))
            frame.pack(side="left", fill="x", expand=True, padx=(0, 10))
            ttk.Label(frame, text=label, style="MetricLabel.TLabel").pack(anchor="w")
            var = tk.StringVar(value="-")
            self.metric_vars[key] = var
            ttk.Label(frame, textvariable=var, style="MetricValue.TLabel").pack(anchor="w", pady=(4, 0))

        main_tabs = ttk.Notebook(self.root)
        main_tabs.pack(fill="both", expand=True, padx=16, pady=(8, 16))

        domestic_frame = ttk.Frame(main_tabs)
        runtime_frame = ttk.Frame(main_tabs, padding=8)
        main_tabs.add(domestic_frame, text="Domestic KR")
        main_tabs.add(runtime_frame, text="Runtime Data")

        panes = ttk.Panedwindow(domestic_frame, orient="vertical")
        panes.pack(fill="both", expand=True)
        top = ttk.Frame(panes)
        bottom = ttk.Notebook(panes)
        panes.add(top, weight=3)
        panes.add(bottom, weight=2)

        columns = ("symbol", "decision", "score", "delta", "avg_ret", "win", "worst_path", "risk", "confidence", "price", "m1", "vol", "d1")
        self.symbol_tree = ttk.Treeview(top, columns=columns, show="headings", selectmode="browse")
        headings = {
            "symbol": "Symbol", "decision": "Decision", "score": "Score", "delta": "Delta",
            "avg_ret": "Avg Ret", "win": "Win", "worst_path": "Worst Path", "risk": "Risk",
            "confidence": "Confidence", "price": "Price", "m1": "1m %", "vol": "1m Vol", "d1": "1d %",
        }
        widths = {
            "symbol": 90, "decision": 120, "score": 70, "delta": 70, "avg_ret": 90,
            "win": 70, "worst_path": 95, "risk": 90, "confidence": 100, "price": 105,
            "m1": 80, "vol": 85, "d1": 80,
        }
        for col in columns:
            self.symbol_tree.heading(col, text=headings[col])
            self.symbol_tree.column(col, width=widths[col], anchor="e" if col not in ("symbol", "decision", "risk", "confidence") else "w")
        self.symbol_tree.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(top, orient="vertical", command=self.symbol_tree.yview)
        self.symbol_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(fill="y", side="right")
        self.symbol_tree.bind("<<TreeviewSelect>>", self._on_symbol_selected)

        self.summary_text = self._add_text_tab(bottom, "Summary")
        self.detail_text = self._add_text_tab(bottom, "Details", monospace=True)
        self.score_canvas = self._add_canvas_tab(bottom, "Score Trend", height=180)
        self.chart_canvas = self._add_canvas_tab(bottom, "Minute Chart", height=260)
        self.paper_tree = self._add_table_tab(bottom, "Paper", ("created", "symbol", "horizon", "anchor", "status", "return", "max", "min", "outcome"))
        self.gpt_text = self._add_text_tab(bottom, "GPT By Symbol")
        self.selected_events_only_var = tk.BooleanVar(value=True)
        self.event_tree = self._add_events_tab(bottom)
        self.context_tree = self._add_table_tab(bottom, "Context", ("time", "scope", "symbol", "section", "reliability", "summary"))
        self.tables_text = self._add_text_tab(bottom, "Tables", monospace=True)
        self.runtime_events_tree = self._add_runtime_table(runtime_frame, "Events", ("time", "symbol", "event", "severity", "value", "message"))
        self.runtime_signals_tree = self._add_runtime_table(runtime_frame, "Signals", ("time", "symbol", "decision", "score", "risk", "reason"))
        self.runtime_context_tree = self._add_runtime_table(runtime_frame, "Context", ("time", "scope", "symbol", "section", "reliability", "summary"))

    def _add_text_tab(self, notebook, title, monospace=False):
        frame = ttk.Frame(notebook, padding=8)
        widget = tk.Text(frame, wrap="word", height=8, font=("Consolas" if monospace else "Segoe UI", 10), relief="solid", borderwidth=1)
        widget.pack(fill="both", expand=True)
        widget.configure(state="disabled")
        notebook.add(frame, text=title)
        return widget

    def _add_canvas_tab(self, notebook, title, height):
        frame = ttk.Frame(notebook, padding=8)
        canvas = tk.Canvas(frame, height=height, bg="#ffffff", highlightthickness=1, highlightbackground="#d9dee7")
        canvas.pack(fill="both", expand=True)
        notebook.add(frame, text=title)
        return canvas

    def _add_events_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=8)
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Checkbutton(
            toolbar,
            text="Selected symbol only",
            variable=self.selected_events_only_var,
            command=self._render_events,
        ).pack(side="left")
        tree = ttk.Treeview(frame, columns=("time", "symbol", "event", "severity", "value", "message"), show="headings")
        for col, width in [("time", 180), ("symbol", 80), ("event", 180), ("severity", 90), ("value", 90), ("message", 520)]:
            tree.heading(col, text=col.title())
            tree.column(col, width=width, anchor="w")
        tree.pack(fill="both", expand=True)
        notebook.add(frame, text="Events By Symbol")
        return tree

    def _add_table_tab(self, notebook, title, columns):
        frame = ttk.Frame(notebook, padding=8)
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col in columns:
            tree.heading(col, text=col.title())
            tree.column(col, width=120, anchor="w")
        tree.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(fill="y", side="right")
        notebook.add(frame, text=title)
        return tree

    def _add_runtime_table(self, parent, title, columns):
        frame = ttk.LabelFrame(parent, text=title, padding=8)
        frame.pack(fill="both", expand=True, pady=(0, 8))
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=7)
        for col in columns:
            tree.heading(col, text=col.title())
            width = 520 if col in ("message", "reason", "summary") else 120
            tree.column(col, width=width, anchor="w")
        tree.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(fill="y", side="right")
        return tree

    def refresh(self):
        try:
            self.snapshot = build_dashboard_snapshot(self.db_path, self.symbols)
            self._render()
            self.status_var.set("Last refresh ok")
        except Exception as exc:
            self.status_var.set("Refresh failed: {}".format(exc))
        self.root.after(self.refresh_ms, self.refresh)

    def _render(self):
        snapshot = self.snapshot
        latest = snapshot.get("latest") or {}
        health = snapshot.get("health") or {}
        warnings = health.get("warnings") or []
        self.meta_var.set("Generated {} | DB {}".format(snapshot.get("generated_at"), snapshot.get("db_path")))
        self.metric_vars["health"].set(health.get("status") or "unknown")
        self.metric_vars["latest_analysis"].set(latest.get("analysis_results") or "none")
        latest_gpt = snapshot.get("latest_gpt_call") or {}
        self.metric_vars["tokens"].set(str(latest_gpt.get("total_tokens") or 0))
        self.metric_vars["warnings"].set(str(len(warnings)))

        self.symbol_tree.delete(*self.symbol_tree.get_children())
        for row in snapshot.get("rows") or []:
            paper = row.get("paper") or {}
            self.symbol_tree.insert("", "end", iid=row.get("code"), values=(
                row.get("code"),
                row.get("action"),
                _fmt(row.get("score"), 0),
                "-",
                _fmt(paper.get("avg_return_60m_pct"), 4, signed=True),
                _fmt(paper.get("win_rate"), 2),
                _fmt(paper.get("avg_max_loss_60m_pct"), 4, signed=True),
                row.get("risk"),
                row.get("confidence"),
                _fmt(row.get("price"), 2),
                _fmt(row.get("change_rate"), 2, signed=True),
                _fmt(row.get("volume_ratio"), 2),
                "-",
            ))
        children = self.symbol_tree.get_children()
        if children and not self.symbol_tree.selection():
            self.symbol_tree.selection_set(children[0])
            self._show_symbol(children[0])

        self._render_events()
        self._fill_paper(self.paper_tree, snapshot.get("recent_paper") or [])
        self._fill_context(self.context_tree, snapshot.get("recent_contexts") or [])
        self._fill_runtime_events(self.runtime_events_tree, snapshot.get("recent_events") or [])
        self._fill_runtime_signals(self.runtime_signals_tree, snapshot.get("recent_signals") or [])
        self._fill_context(self.runtime_context_tree, snapshot.get("recent_contexts") or [])
        self._set_text(self.tables_text, self._tables_text())

    def _on_symbol_selected(self, _event=None):
        selection = self.symbol_tree.selection()
        if selection:
            self._show_symbol(selection[0])

    def _show_symbol(self, code):
        row = None
        for item in self.snapshot.get("rows") or []:
            if item.get("code") == code:
                row = item
                break
        if not row:
            return
        self._set_text(self.summary_text, self._summary_text(row))
        self._set_text(self.detail_text, self._detail_text(row))
        self._draw_score_history(row)
        self._draw_minute_chart(row)
        self._set_text(self.gpt_text, row.get("gpt_result") or "No GPT result for {}".format(code))
        self._render_events()
        self._fill_paper(self.paper_tree, row.get("paper_rows") or [])
        self._fill_context(self.context_tree, row.get("contexts") or [])

    def _summary_text(self, row):
        readable = _readable_summary_text(row)
        if readable:
            return readable
        return "\n".join([
            "Symbol: {}".format(row.get("code")),
            "Decision: {} | Score: {}".format(row.get("action"), _fmt(row.get("score"), 0)),
            "Risk: {} | Price: {}".format(row.get("risk"), _fmt(row.get("price"), 2)),
            "Latest tick: {}".format(row.get("tick_time") or "-"),
        ])

    def _detail_text(self, row):
        paper = row.get("paper") or {}
        lines = [
            "Code: {} {}".format(row.get("code"), row.get("name") or ""),
            "Action: {} | Score: {} | Risk: {}".format(row.get("action"), _fmt(row.get("score"), 0), row.get("risk")),
            "Price: {} | Latest tick: {}".format(_fmt(row.get("price"), 2), row.get("tick_time")),
            "Analysis: {}".format(row.get("analysis_time") or "-"),
            "",
            "Paper Feedback",
            "  evaluated_count: {}".format(paper.get("evaluated_count", 0)),
            "  win_rate: {}".format(_fmt(paper.get("win_rate"), 4)),
            "  avg_return_60m_pct: {}".format(_fmt(paper.get("avg_return_60m_pct"), 4, signed=True)),
            "  avg_max_gain_60m_pct: {}".format(_fmt(paper.get("avg_max_gain_60m_pct"), 4, signed=True)),
            "  avg_max_loss_60m_pct: {}".format(_fmt(paper.get("avg_max_loss_60m_pct"), 4, signed=True)),
            "",
            "Market Context JSON",
            _pretty_json(row.get("market_context_json")),
            "",
            "Summary JSON",
            _pretty_json(row.get("summary_json")),
            "",
            "Recent Signals",
            _pretty_json(row.get("signals")),
        ]
        return "\n".join(lines)

    def _tables_text(self):
        lines = ["Tables"]
        for key, value in sorted((self.snapshot.get("tables") or {}).items()):
            lines.append("{:<32} {}".format(key, value))
        lines.append("")
        lines.append("Health")
        health = self.snapshot.get("health") or {}
        for key, value in sorted((health.get("ages_min") or {}).items()):
            lines.append("{:<32} {}".format(key, value))
        if health.get("warnings"):
            lines.append("")
            lines.append("Warnings")
            lines.extend(health.get("warnings") or [])
        return "\n".join(lines)

    def apply_symbols(self):
        symbols = normalize_symbols(self.symbols_var.get().split(","))
        if not symbols:
            self.status_var.set("Symbols cannot be empty")
            return
        self.symbols = symbols
        save_symbols(symbols, self.symbols_path)
        self.status_var.set("Saved symbols: {} -> {}".format(",".join(symbols), self.symbols_path))
        self.symbol_tree.selection_remove(*self.symbol_tree.selection())
        self.refresh()

    def reload_symbols(self):
        symbols = load_symbols(self.symbols_path) or list(DEFAULT_SYMBOLS)
        self.symbols = symbols
        self.symbols_var.set(",".join(symbols))
        self.status_var.set("Reloaded symbols: {}".format(",".join(symbols)))
        self.symbol_tree.selection_remove(*self.symbol_tree.selection())
        self.refresh()

    def export_html(self):
        try:
            os.makedirs(os.path.dirname(DEFAULT_HTML_PATH), exist_ok=True)
            with open(DEFAULT_HTML_PATH, "w", encoding="utf-8") as handle:
                handle.write(render_dashboard_html(self.snapshot))
            self.status_var.set("Exported {}".format(DEFAULT_HTML_PATH))
        except Exception as exc:
            self.status_var.set("Export failed: {}".format(exc))

    def open_html(self):
        self.export_html()
        if os.path.exists(DEFAULT_HTML_PATH):
            webbrowser.open("file:///" + os.path.abspath(DEFAULT_HTML_PATH).replace("\\", "/"))

    def _set_text(self, widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text or "")
        widget.configure(state="disabled")

    def _fill_events(self, tree, rows):
        tree.delete(*tree.get_children())
        for idx, row in enumerate(rows):
            tree.insert("", "end", iid=str(idx), values=(
                row.get("detected_at"), row.get("code"), row.get("event_type"),
                row.get("timeframe"), _fmt(row.get("value"), 3), row.get("message"),
            ))

    def _fill_signals(self, tree, rows):
        tree.delete(*tree.get_children())
        for idx, row in enumerate(rows):
            tree.insert("", "end", iid=str(idx), values=(
                row.get("detected_at"), row.get("code"), row.get("action_hint"),
                _fmt(row.get("confidence_score"), 0), row.get("risk_level"), row.get("reason_json"),
            ))

    def _fill_paper(self, tree, rows):
        tree.delete(*tree.get_children())
        for idx, row in enumerate(rows):
            tree.insert("", "end", iid=str(idx), values=(
                row.get("evaluated_at"), row.get("code"), "60", _fmt(row.get("entry_price"), 2),
                "evaluated", _fmt(row.get("return_60m_pct"), 4, signed=True),
                _fmt(row.get("max_gain_60m_pct"), 4, signed=True),
                _fmt(row.get("max_loss_60m_pct"), 4, signed=True),
                row.get("outcome_label") or "",
            ))

    def _fill_context(self, tree, rows):
        tree.delete(*tree.get_children())
        for idx, row in enumerate(rows):
            tree.insert("", "end", iid=str(idx), values=(
                row.get("collected_at"), row.get("scope"), row.get("code") or "GLOBAL",
                row.get("section"), row.get("reliability"), row.get("summary"),
            ))

    def _fill_runtime_events(self, tree, rows):
        tree.delete(*tree.get_children())
        for idx, row in enumerate(rows):
            tree.insert("", "end", iid=str(idx), values=(
                row.get("detected_at"),
                row.get("code"),
                row.get("event_type"),
                row.get("timeframe"),
                _fmt(row.get("value"), 2),
                row.get("message"),
            ))

    def _fill_runtime_signals(self, tree, rows):
        tree.delete(*tree.get_children())
        for idx, row in enumerate(rows):
            tree.insert("", "end", iid=str(idx), values=(
                row.get("detected_at"),
                row.get("code"),
                row.get("action_hint"),
                _fmt(row.get("confidence_score"), 0),
                row.get("risk_level"),
                row.get("reason_json"),
            ))

    def _render_events(self):
        if not hasattr(self, "event_tree"):
            return
        selected = None
        selection = self.symbol_tree.selection() if hasattr(self, "symbol_tree") else []
        if selection:
            selected = selection[0]
        if self.selected_events_only_var.get() and selected:
            rows = []
            for item in self.snapshot.get("rows") or []:
                if item.get("code") == selected:
                    rows = item.get("events") or []
                    break
        else:
            rows = self.snapshot.get("recent_events") or []
        self.event_tree.delete(*self.event_tree.get_children())
        for idx, row in enumerate(rows):
            self.event_tree.insert("", "end", iid=str(idx), values=(
                row.get("detected_at"),
                row.get("code"),
                row.get("event_type"),
                row.get("timeframe"),
                _fmt(row.get("value"), 2),
                row.get("message"),
            ))

    def _draw_score_history(self, row):
        canvas = self.score_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 400)
        height = max(canvas.winfo_height(), 180)
        pad = 34
        code = (row or {}).get("code") or "-"
        canvas.create_text(12, 12, anchor="nw", text="Interest score history: {}".format(code), fill="#1d2430", font=("Segoe UI", 10, "bold"))
        canvas.create_line(pad, height - pad, width - pad, height - pad, fill="#d9dee7")
        canvas.create_line(pad, pad, pad, height - pad, fill="#d9dee7")
        for score in (0, 50, 100):
            y = height - pad - (score / 100.0) * (height - 2 * pad)
            canvas.create_line(pad, y, width - pad, y, fill="#eef2f6")
            canvas.create_text(8, y, anchor="w", text=str(score), fill="#667085", font=("Segoe UI", 8))
        history = (row or {}).get("score_history") or []
        points = []
        for idx, item in enumerate(history):
            score = item.get("confidence_score")
            if score is None:
                continue
            x = pad if len(history) <= 1 else pad + (idx / float(len(history) - 1)) * (width - 2 * pad)
            y = height - pad - (float(score) / 100.0) * (height - 2 * pad)
            points.append((x, y, item))
        if len(points) >= 2:
            coords = []
            for x, y, _item in points:
                coords.extend([x, y])
            canvas.create_line(*coords, fill="#1b64d8", width=2)
        for x, y, item in points:
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#1b64d8", outline="#1b64d8")
            canvas.create_text(x, y - 12, text=str(item.get("confidence_score")), fill="#1d2430", font=("Segoe UI", 8))

    def _draw_minute_chart(self, row):
        canvas = self.chart_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 520)
        height = max(canvas.winfo_height(), 260)
        pad_l = 54
        pad_r = 24
        pad_t = 28
        pad_b = 34
        code = (row or {}).get("code") or "-"
        series = (row or {}).get("tick_series") or []
        canvas.create_text(12, 10, anchor="nw", text="1m close chart: {}".format(code), fill="#1d2430", font=("Segoe UI", 10, "bold"))
        values = [_to_float(item.get("price")) for item in series if _to_float(item.get("price")) > 0]
        if len(values) < 2:
            canvas.create_text(width / 2, height / 2, text="Not enough 1m close data", fill="#667085", font=("Segoe UI", 11))
            return
        low = min(values)
        high = max(values)
        if high <= low:
            high = low + 1.0
        x0 = pad_l
        x1 = width - pad_r
        y0 = pad_t
        y1 = height - pad_b

        def y_for(price):
            return y1 - ((price - low) / (high - low)) * (y1 - y0)

        def x_for(index):
            return x0 + (index / float(len(values) - 1)) * (x1 - x0)

        canvas.create_rectangle(x0, y0, x1, y1, outline="#d9dee7")
        levels = [
            ("R", high, "#b42318"),
            ("Fib 23.6", high - (high - low) * 0.236, "#b54708"),
            ("Fib 38.2", high - (high - low) * 0.382, "#b54708"),
            ("Fib 50.0", high - (high - low) * 0.500, "#667085"),
            ("Fib 61.8", high - (high - low) * 0.618, "#b54708"),
            ("S", low, "#147a42"),
        ]
        for label, price, color in levels:
            y = y_for(price)
            canvas.create_line(x0, y, x1, y, fill=color, dash=(4, 3))
            canvas.create_text(8, y, anchor="w", text="{} {:.2f}".format(label, price), fill=color, font=("Segoe UI", 8))
        coords = []
        for idx, price in enumerate(values):
            coords.extend([x_for(idx), y_for(price)])
        canvas.create_line(*coords, fill="#1b64d8", width=2)
        last_x = x_for(len(values) - 1)
        last_y = y_for(values[-1])
        canvas.create_oval(last_x - 4, last_y - 4, last_x + 4, last_y + 4, fill="#1b64d8", outline="#1b64d8")
        canvas.create_text(last_x - 4, last_y - 14, anchor="e", text="{:.2f}".format(values[-1]), fill="#1d2430", font=("Segoe UI", 9, "bold"))


def _symbols_from_db(conn):
    rows = conn.execute("""
        SELECT code FROM signal_logs
        UNION
        SELECT code FROM analysis_results
        UNION
        SELECT code FROM ticks
        ORDER BY code
    """).fetchall()
    codes = [row["code"] for row in rows if row["code"]]
    preferred = [code for code in DEFAULT_SYMBOLS if code in codes]
    others = [code for code in codes if code not in preferred]
    return preferred + others[:6]


def _table_counts(conn):
    result = {}
    for table in [
        "ticks", "analysis_results", "event_logs", "signal_logs",
        "gpt_call_logs", "paper_trade_results", "market_context_snapshots",
        "notification_logs", "historical_bars",
    ]:
        try:
            result[table] = conn.execute("SELECT COUNT(1) FROM {}".format(table)).fetchone()[0]
        except sqlite3.Error:
            result[table] = None
    return result


def _latest_times(conn):
    mapping = {
        "ticks": "received_at",
        "analysis_results": "analyzed_at",
        "event_logs": "detected_at",
        "signal_logs": "detected_at",
        "gpt_call_logs": "started_at",
        "paper_trade_results": "evaluated_at",
        "market_context_snapshots": "collected_at",
    }
    result = {}
    for table, column in mapping.items():
        try:
            result[table] = conn.execute("SELECT MAX({}) FROM {}".format(column, table)).fetchone()[0]
        except sqlite3.Error:
            result[table] = None
    return result


def _health(latest):
    now = datetime.now()
    ages = {}
    warnings = []
    for key in ("ticks", "analysis_results", "gpt_call_logs", "market_context_snapshots"):
        age = _age_minutes(now, latest.get(key))
        ages[key] = age
        if latest.get(key) is None:
            warnings.append("{}=missing".format(key))
        elif key == "ticks" and age is not None and age > 60:
            warnings.append("latest_tick_age_min={}".format(round(age, 2)))
    return {
        "status": "ok" if not warnings else "warning",
        "warnings": warnings,
        "ages_min": ages,
    }


def _latest_tick(conn, code):
    return _row(conn, """
        SELECT code, trade_time, price, change_rate, acc_volume, tick_volume,
               open_price, high_price, low_price, strength, received_at
        FROM ticks
        WHERE code = ?
        ORDER BY received_at DESC, id DESC
        LIMIT 1
    """, (code,))


def _latest_signal(conn, code):
    return _row(conn, """
        SELECT *
        FROM signal_logs
        WHERE code = ?
        ORDER BY detected_at DESC, id DESC
        LIMIT 1
    """, (code,))


def _latest_analysis(conn, code):
    return _row(conn, """
        SELECT *
        FROM analysis_results
        WHERE code = ?
        ORDER BY analyzed_at DESC, id DESC
        LIMIT 1
    """, (code,))


def _paper_summary(conn, code):
    row = conn.execute("""
        SELECT COUNT(1) AS evaluated_count,
               SUM(CASE WHEN return_60m_pct > 0 THEN 1 ELSE 0 END) AS wins,
               AVG(return_60m_pct) AS avg_return_60m_pct,
               AVG(max_gain_60m_pct) AS avg_max_gain_60m_pct,
               AVG(max_loss_60m_pct) AS avg_max_loss_60m_pct
        FROM paper_trade_results
        WHERE code = ?
    """, (code,)).fetchone()
    count = int(row["evaluated_count"] or 0)
    wins = int(row["wins"] or 0)
    return {
        "evaluated_count": count,
        "win_rate": round(wins / count, 4) if count else 0.0,
        "avg_return_60m_pct": round(_to_float(row["avg_return_60m_pct"]), 4),
        "avg_max_gain_60m_pct": round(_to_float(row["avg_max_gain_60m_pct"]), 4),
        "avg_max_loss_60m_pct": round(_to_float(row["avg_max_loss_60m_pct"]), 4),
    }


def _recent_events(conn, code=None, limit=30):
    where = ""
    params = []
    if code:
        where = "WHERE code = ?"
        params.append(code)
    params.append(int(limit))
    rows = conn.execute("""
        SELECT detected_at, code, name, event_type, timeframe, message, value,
               gpt_requested, skip_reason
        FROM event_logs
        {where}
        ORDER BY detected_at DESC, id DESC
        LIMIT ?
    """.format(where=where), params).fetchall()
    return [dict(row) for row in rows]


def _recent_signals(conn, code=None, limit=30):
    where = ""
    params = []
    if code:
        where = "WHERE code = ?"
        params.append(code)
    params.append(int(limit))
    rows = conn.execute("""
        SELECT detected_at, code, name, action_hint, confidence_score, risk_level,
               current_price, stop_loss, target_1, target_2, reason_json
        FROM signal_logs
        {where}
        ORDER BY detected_at DESC, id DESC
        LIMIT ?
    """.format(where=where), params).fetchall()
    return [dict(row) for row in rows]


def _recent_paper(conn, code=None, limit=30):
    where = ""
    params = []
    if code:
        where = "WHERE code = ?"
        params.append(code)
    params.append(int(limit))
    rows = conn.execute("""
        SELECT evaluated_at, code, entry_time, entry_price, return_5m_pct,
               return_10m_pct, return_30m_pct, return_60m_pct,
               max_gain_60m_pct, max_loss_60m_pct, outcome_label
        FROM paper_trade_results
        {where}
        ORDER BY evaluated_at DESC, id DESC
        LIMIT ?
    """.format(where=where), params).fetchall()
    return [dict(row) for row in rows]


def _recent_contexts(conn, code=None, limit=30):
    where = ""
    params = []
    if code:
        where = "WHERE code = ? OR scope = 'global'"
        params.append(code)
    params.append(int(limit))
    rows = conn.execute("""
        SELECT collected_at, scope, code, section, source, asof, reliability,
               weight, summary, payload_json
        FROM market_context_snapshots
        {where}
        ORDER BY collected_at DESC, id DESC
        LIMIT ?
    """.format(where=where), params).fetchall()
    return [dict(row) for row in rows]


def _recent_ticks(conn, code=None, limit=120):
    rows = conn.execute("""
        SELECT received_at, code, price, change_rate, acc_volume, tick_volume
        FROM ticks
        WHERE code = ?
        ORDER BY received_at DESC, id DESC
        LIMIT ?
    """, (code, int(limit))).fetchall()
    return [dict(row) for row in reversed(rows)]


def _recent_signal_scores(conn, code=None, limit=12):
    rows = conn.execute("""
        SELECT detected_at, code, action_hint, confidence_score, risk_level
        FROM signal_logs
        WHERE code = ?
        ORDER BY detected_at DESC, id DESC
        LIMIT ?
    """, (code, int(limit))).fetchall()
    return [dict(row) for row in reversed(rows)]


def _latest_gpt_call(conn):
    return _row(conn, """
        SELECT *
        FROM gpt_call_logs
        ORDER BY started_at DESC, id DESC
        LIMIT 1
    """, ())


def _row(conn, query, params):
    row = conn.execute(query, params).fetchone()
    return dict(row) if row else {}


def _symbol_html(row):
    paper = row.get("paper") or {}
    risk = str(row.get("risk") or "unknown").upper()
    return """<tr>
<td><strong>{code}</strong><div class="muted">{name}</div></td>
<td><span class="pill">{action}</span></td>
<td class="num">{score}</td>
<td class="num muted">-</td>
<td class="num {avg_class}">{avg_ret}</td>
<td class="num">{win}</td>
<td class="num {worst_class}">{worst_path}</td>
<td><span class="pill risk-{risk}">{risk}</span></td>
<td>{confidence}</td>
<td class="num">{price}</td>
<td class="num {m1_class}">{m1}</td>
<td class="num">{vol}</td>
<td class="num muted">-</td>
</tr>""".format(
        code=_e(row.get("code")),
        name=_e(row.get("name")),
        action=_e(row.get("action")),
        score=_fmt(row.get("score"), 0),
        avg_class=_num_class(paper.get("avg_return_60m_pct")),
        avg_ret=_fmt(paper.get("avg_return_60m_pct"), 4, signed=True),
        win=_fmt(paper.get("win_rate"), 4),
        worst_class=_num_class(paper.get("avg_max_loss_60m_pct")),
        worst_path=_fmt(paper.get("avg_max_loss_60m_pct"), 4, signed=True),
        risk=_e(risk),
        confidence=_e(row.get("confidence")),
        price=_fmt(row.get("price"), 2),
        m1_class=_num_class(row.get("change_rate")),
        m1=_fmt(row.get("change_rate"), 2, signed=True),
        vol=_fmt(row.get("volume_ratio"), 2),
    )


def _event_html(row):
    return """<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td class="num">{}</td><td>{}</td></tr>""".format(
        _e(row.get("detected_at")), _e(row.get("code")), _e(row.get("event_type")),
        _e(row.get("timeframe")), _fmt(row.get("value"), 3), _e(row.get("message")),
    )


def _signal_html(row):
    return """<tr><td>{}</td><td>{}</td><td>{}</td><td class="num">{}</td><td>{}</td><td>{}</td></tr>""".format(
        _e(row.get("detected_at")), _e(row.get("code")), _e(row.get("action_hint")),
        _fmt(row.get("confidence_score"), 0), _e(row.get("risk_level")),
        _e(row.get("reason_json")),
    )


def _context_html(row):
    return """<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>""".format(
        _e(row.get("collected_at")), _e(row.get("scope")), _e(row.get("code") or "GLOBAL"),
        _e(row.get("section")), _e(row.get("reliability")), _e(row.get("summary")),
    )


def _paper_html(row):
    return """<tr><td>{}</td><td>{}</td><td class="num">60</td><td class="num">{}</td><td>evaluated</td><td class="num {}">{}</td><td class="num {}">{}</td><td class="num {}">{}</td><td>{}</td></tr>""".format(
        _e(row.get("evaluated_at")),
        _e(row.get("code")),
        _fmt(row.get("entry_price"), 2),
        _num_class(row.get("return_60m_pct")),
        _fmt(row.get("return_60m_pct"), 4, signed=True),
        _num_class(row.get("max_gain_60m_pct")),
        _fmt(row.get("max_gain_60m_pct"), 4, signed=True),
        _num_class(row.get("max_loss_60m_pct")),
        _fmt(row.get("max_loss_60m_pct"), 4, signed=True),
        _e(row.get("outcome_label") or ""),
    )


def _age_minutes(now, value):
    dt = _parse_dt(value)
    if not dt:
        return None
    return round(max(0.0, (now - dt).total_seconds() / 60.0), 4)


def _parse_dt(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _pretty_json(value):
    if not value:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    try:
        return json.dumps(json.loads(value), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)


def _readable_summary_text(row):
    """Render selected-symbol summary as scan-friendly text instead of raw JSON."""
    summary = _load_json(row.get("summary_json"))
    if not summary:
        return ""

    signal = summary.get("validation_signal") or {}
    paper = row.get("paper") or {}
    lines = [
        "{} {}".format(row.get("code"), row.get("name") or summary.get("name") or "").strip(),
        "Decision: {} | Score: {} | Risk: {}".format(
            row.get("action") or signal.get("action_hint") or "none",
            _fmt(row.get("score") if row.get("score") is not None else signal.get("confidence_score"), 0),
            row.get("risk") or signal.get("risk_level") or "unknown",
        ),
        "Price: {} | Tick: {} | Analysis: {}".format(
            _fmt(row.get("price") if row.get("price") is not None else _latest_value(summary, "close"), 0),
            row.get("tick_time") or "-",
            row.get("analysis_time") or "-",
        ),
    ]

    event_text = _events_text(summary)
    if event_text:
        lines.extend(["", "Events", event_text])

    if signal:
        lines.extend([
            "",
            "Observation Anchors",
            "  lower: {} | upper1: {} | upper2: {}".format(
                _fmt(signal.get("stop_loss"), 0),
                _fmt(signal.get("target_1"), 0),
                _fmt(signal.get("target_2"), 0),
            ),
        ])
        reasons = [str(item) for item in (signal.get("reasons") or []) if str(item).strip()]
        if reasons:
            lines.append("  reason: {}".format("; ".join(reasons[:3])))

    timeframes = summary.get("timeframes") or {}
    if timeframes:
        lines.extend(["", "Timeframes"])
    for label in ("1m", "3m", "5m"):
        timeframe = timeframes.get(label) or {}
        if not timeframe:
            continue
        latest = timeframe.get("latest") or {}
        momentum = timeframe.get("momentum") or {}
        volume = timeframe.get("volume") or {}
        vwap = timeframe.get("vwap") or {}
        trend = timeframe.get("trend") or {}
        lines.append(
            "  {label}: close {close} ({ret}) | RSI {rsi} | VWAP {vwap} | vol20 {vol} | up/down {up}/{down}".format(
                label=label,
                close=_fmt(latest.get("close"), 0),
                ret=_fmt(latest.get("return_1bar_pct"), 3, signed=True),
                rsi=_fmt(momentum.get("rsi14"), 2),
                vwap=_fmt(vwap.get("vwap_distance_pct"), 3, signed=True),
                vol=_fmt(volume.get("volume_ratio_20"), 2),
                up=_fmt(trend.get("consecutive_up_bars"), 0),
                down=_fmt(trend.get("consecutive_down_bars"), 0),
            )
        )

    if paper:
        lines.extend([
            "",
            "Paper Feedback",
            "  evaluated: {} | win: {} | avg60: {} | worst60: {}".format(
                paper.get("evaluated_count", 0),
                _fmt(paper.get("win_rate"), 2),
                _fmt(paper.get("avg_return_60m_pct"), 4, signed=True),
                _fmt(paper.get("avg_max_loss_60m_pct"), 4, signed=True),
            ),
        ])

    market_snapshot = summary.get("market_snapshot") or {}
    if market_snapshot:
        lines.extend([
            "",
            "Market Snapshot",
            "  change: {} | open/high/low: {}/{}/{} | strength: {}".format(
                _fmt(market_snapshot.get("change_rate"), 2, signed=True),
                _fmt(market_snapshot.get("day_open"), 0),
                _fmt(market_snapshot.get("day_high"), 0),
                _fmt(market_snapshot.get("day_low"), 0),
                _fmt(market_snapshot.get("strength"), 2),
            ),
        ])

    return "\n".join(lines)


def _load_json(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def _events_text(summary):
    events = summary.get("events") or []
    if not events:
        return ""
    parts = []
    for event in events[:5]:
        event_type = event.get("type") or "event"
        value = event.get("value")
        timeframe = event.get("timeframe")
        suffix = []
        if timeframe:
            suffix.append(str(timeframe))
        if value is not None:
            suffix.append(_fmt(value, 3))
        parts.append("{}{}".format(event_type, " ({})".format(", ".join(suffix)) if suffix else ""))
    return "  " + "; ".join(parts)


def _latest_value(summary, key):
    timeframe = ((summary.get("timeframes") or {}).get("1m") or {})
    return (timeframe.get("latest") or {}).get(key)


def _fmt(value, decimals=2, signed=False):
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if decimals == 0:
        text = str(int(round(number)))
    else:
        text = ("{0:." + str(decimals) + "f}").format(number)
    if signed and number > 0:
        return "+" + text
    return text


def _to_float(value):
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _num_class(value):
    number = _to_float(value)
    if number > 0:
        return "pos"
    if number < 0:
        return "neg"
    return "muted"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _e(value):
    return html.escape(str(value if value is not None else ""))


def normalize_symbols(symbols):
    cleaned = []
    for item in symbols or []:
        value = str(item).strip()
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned


def load_symbols(path=DEFAULT_SYMBOLS_PATH):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        symbols = payload.get("symbols") if isinstance(payload, dict) else payload
        return normalize_symbols(symbols)
    except (IOError, OSError, TypeError, ValueError):
        return []


def save_symbols(symbols, path=DEFAULT_SYMBOLS_PATH):
    cleaned = normalize_symbols(symbols)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = {
        "label": "Domestic KR",
        "market": "KR",
        "symbols": cleaned,
        "symbol_count": len(cleaned),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "orders_enabled": False,
        "note": "Saved from Kiwoom dashboard UI. Collection processes may need restart to change live collection symbols.",
    }
    tmp_path = os.path.abspath(path) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_path, os.path.abspath(path))
    return cleaned


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open Kiwoom focused read-only dashboard.")
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--symbols-path", default=DEFAULT_SYMBOLS_PATH)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--refresh-sec", type=int, default=30)
    parser.add_argument("--export-html", action="store_true")
    parser.add_argument("--html", default=DEFAULT_HTML_PATH)
    args = parser.parse_args(argv)

    if args.symbols:
        symbols = normalize_symbols(args.symbols.split(","))
        save_symbols(symbols, args.symbols_path)
    else:
        symbols = load_symbols(args.symbols_path) or list(DEFAULT_SYMBOLS)
    if args.export_html:
        snapshot = build_dashboard_snapshot(args.db, symbols=symbols)
        os.makedirs(os.path.dirname(os.path.abspath(args.html)), exist_ok=True)
        with open(args.html, "w", encoding="utf-8") as handle:
            handle.write(render_dashboard_html(snapshot))
        print("KIWOOM_DASHBOARD_HTML={}".format(os.path.abspath(args.html)))
        return 0

    root = tk.Tk()
    KiwoomFocusedDashboard(root, symbols=symbols, db_path=args.db, refresh_sec=args.refresh_sec, symbols_path=args.symbols_path)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
