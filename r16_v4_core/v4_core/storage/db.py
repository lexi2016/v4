"""Unified SQLite storage with immutable asof_date QFQ snapshots, 4-domain indexes & 6-slot execution_ref."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator

QFQ_KB_COLUMNS = ("pre_close", "pct_chg", "user_v1_sell_signal_daily")
QFQ_BAR_COLUMNS = ("open", "high", "low", "close", "volume", "amount", "adj_factor")

_PREFIX_SYMBOL_RE = re.compile(r"^(SH|SZ|BJ|HK)[\._]?([0-9A-Za-z]+)$", re.IGNORECASE)
_SUFFIX_SYMBOL_RE = re.compile(r"^([0-9A-Za-z]+)\.(SH|SZ|BJ|HK)$", re.IGNORECASE)


def normalize_symbol(symbol: str) -> str:
    """Canonicalize symbol formats (e.g. SZ.301252 / sz301252 / 301252.SZ -> 301252.SZ)."""
    raw = str(symbol or "").strip()
    if not raw:
        return ""
    m_suf = _SUFFIX_SYMBOL_RE.match(raw)
    if m_suf:
        code, exch = m_suf.group(1), m_suf.group(2).upper()
        if exch == "HK" and code.isdigit():
            code = code.zfill(5)
        return f"{code}.{exch}"
    m_pre = _PREFIX_SYMBOL_RE.match(raw)
    if m_pre:
        exch, code = m_pre.group(1).upper(), m_pre.group(2)
        if exch == "HK" and code.isdigit():
            code = code.zfill(5)
        return f"{code}.{exch}"
    return raw.upper()



def normalize_iso_date(value: str) -> str:
    """Normalize YYYYMMDD or YYYY-MM-DD to YYYY-MM-DD."""
    raw = str(value or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def normalize_compact_date(value: str) -> str:
    """Normalize YYYY-MM-DD or YYYYMMDD to YYYYMMDD."""
    raw = str(value or "").strip()
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return raw.replace("-", "")
    return raw


def date_variants(value: str) -> tuple[str, ...]:
    iso = normalize_iso_date(value)
    compact = normalize_compact_date(value)
    return tuple(dict.fromkeys([str(value), iso, compact]))


SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS daily_bars (
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    amount REAL NOT NULL,
    pre_close REAL,
    pre_close_basis TEXT,
    pre_close_trade_date TEXT,
    PRIMARY KEY (market, symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_bars_date ON daily_bars (market, trade_date);

CREATE TABLE IF NOT EXISTS adj_factors (
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    adj_factor REAL NOT NULL,
    PRIMARY KEY (market, symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_adj_factors_sym ON adj_factors (market, symbol, trade_date);

CREATE TABLE IF NOT EXISTS qfq_bars (
    market TEXT NOT NULL,
    asof_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    amount REAL NOT NULL,
    adj_factor REAL NOT NULL,
    pre_close REAL,
    pct_chg REAL,
    user_v1_sell_signal_daily INTEGER,
    PRIMARY KEY (market, asof_date, symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_qfq_bars_asof ON qfq_bars (market, asof_date, symbol, trade_date);

CREATE TABLE IF NOT EXISTS quarantine_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS a_daily_publications (
    trade_date TEXT PRIMARY KEY,
    checkpoint_sha256 TEXT NOT NULL,
    delta_path TEXT NOT NULL,
    delta_sha256 TEXT NOT NULL,
    bars_projection_sha256 TEXT NOT NULL,
    accepted_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS top200_daily (
    trade_date TEXT NOT NULL,
    rank INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    close REAL NOT NULL,
    pct_chg REAL NOT NULL,
    amount REAL NOT NULL,
    daily_gain_rank_eligibility TEXT NOT NULL,
    historical_pit INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (trade_date, rank)
);

CREATE TABLE IF NOT EXISTS workbench_selections (
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    selection_group TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS workbench_scores (
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    selection_group TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    score REAL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    PRIMARY KEY (trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS task_runs (
    run_id TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    step TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_master (
    trade_date TEXT NOT NULL,
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    display_name TEXT NOT NULL,
    industry TEXT NOT NULL DEFAULT '',
    source_ref TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (trade_date, market, symbol)
);
CREATE INDEX IF NOT EXISTS idx_security_master_sym ON security_master (symbol, trade_date);

CREATE TABLE IF NOT EXISTS stage_selections (
    trade_date TEXT NOT NULL,
    stage TEXT NOT NULL,
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    rank INTEGER NOT NULL DEFAULT 0,
    signal_date TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'READY',
    execution_ref TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (trade_date, stage, market, symbol)
);
CREATE INDEX IF NOT EXISTS idx_stage_selections_lookup ON stage_selections (trade_date, stage, market);

CREATE TABLE IF NOT EXISTS preselection_pools (
    trade_date TEXT NOT NULL,
    pool_name TEXT NOT NULL,
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'READY',
    payload_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (trade_date, pool_name, market, symbol)
);
CREATE INDEX IF NOT EXISTS idx_preselection_pools_date ON preselection_pools (trade_date, pool_name);

CREATE TABLE IF NOT EXISTS research_materials (
    record_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    publish_date TEXT NOT NULL DEFAULT '',
    collected_date TEXT NOT NULL DEFAULT '',
    applicable_date TEXT NOT NULL DEFAULT '',
    market TEXT NOT NULL DEFAULT 'A',
    symbol TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    owner_ref TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_research_materials_type_date ON research_materials (source_type, trade_date);
CREATE INDEX IF NOT EXISTS idx_research_materials_symbol ON research_materials (symbol, trade_date);

CREATE TABLE IF NOT EXISTS announcements (
    event_id TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    scope_id TEXT NOT NULL DEFAULT 'default',
    market TEXT NOT NULL DEFAULT 'A',
    symbol TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    publish_date TEXT NOT NULL DEFAULT '',
    owner_ref TEXT NOT NULL DEFAULT '',
    product_sha256 TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_announcements_date_scope ON announcements (trade_date, scope_id);

CREATE TABLE IF NOT EXISTS announcement_jobs (
    job_id TEXT PRIMARY KEY,
    target_date TEXT NOT NULL,
    state TEXT NOT NULL,
    source_job_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS manual_collection_jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS review_records (
    trade_date TEXT NOT NULL,
    plan_run_id TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL DEFAULT 'READY',
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (trade_date, plan_run_id)
);

CREATE TABLE IF NOT EXISTS manager_runs (
    run_id TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS slot_executions (
    trade_date TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    slot_name TEXT NOT NULL,
    schedule_time TEXT NOT NULL,
    status TEXT NOT NULL,
    execution_ref TEXT NOT NULL,
    run_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (trade_date, slot_id)
);
CREATE INDEX IF NOT EXISTS idx_slot_executions_date ON slot_executions (trade_date);
"""


class V4Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.execute("BEGIN IMMEDIATE")
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(workbench_selections)").fetchall()}
            if "display_name" not in cols:
                conn.execute("ALTER TABLE workbench_selections ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
            daily_cols = {r["name"] for r in conn.execute("PRAGMA table_info(daily_bars)")}
            for name in ("pre_close_basis", "pre_close_trade_date"):
                if name not in daily_cols:
                    conn.execute(f"ALTER TABLE daily_bars ADD COLUMN {name} TEXT")
            qfq_cols = {r["name"] for r in conn.execute("PRAGMA table_info(qfq_bars)")}
            optional_qfq_columns = (("pre_close", "REAL"), ("pct_chg", "REAL"),
                                    ("user_v1_sell_signal_daily", "INTEGER"))
            for name, kind in optional_qfq_columns:
                if name not in qfq_cols:
                    conn.execute(f"ALTER TABLE qfq_bars ADD COLUMN {name} {kind}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def upsert_daily_bars(
        self, rows: list[dict[str, Any]], *, connection: sqlite3.Connection | None = None,
        native_tdx: bool = False,
    ) -> int:
        if not rows:
            return 0
        sql = """
        INSERT INTO daily_bars (market, symbol, trade_date, open, high, low, close, volume, amount, pre_close,
                                pre_close_basis, pre_close_trade_date)
        VALUES (:market, :symbol, :trade_date, :open, :high, :low, :close, :volume, :amount, :pre_close,
                :pre_close_basis, :pre_close_trade_date)
        ON CONFLICT(market, symbol, trade_date) DO UPDATE SET
            open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
            volume=excluded.volume, amount=excluded.amount, pre_close=excluded.pre_close,
            pre_close_basis=excluded.pre_close_basis, pre_close_trade_date=excluded.pre_close_trade_date
        """
        normalized = [{
            **row,
            "pre_close_basis": "TDX_PRIOR_RAW" if native_tdx else None,
            "pre_close_trade_date": row.get("pre_close_trade_date") if native_tdx else None,
        } for row in rows]
        with (nullcontext(connection) if connection is not None else self.connect()) as conn:
            conn.executemany(sql, normalized)
        return len(rows)

    def get_a_daily_reference_inputs(self, trade_date: str) -> list[dict[str, Any]]:
        """Read the target slice, one prior close per symbol and the paired factors."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT target.symbol, target.close, target.amount,
                          CASE WHEN target.pre_close_basis='TDX_PRIOR_RAW' THEN target.pre_close_trade_date
                               ELSE prior.trade_date END AS prior_date,
                          CASE WHEN target.pre_close_basis='TDX_PRIOR_RAW' THEN target.pre_close
                               ELSE prior.close END AS prior_raw_close,
                          pf.adj_factor AS prior_factor, tf.adj_factor AS target_factor
                   FROM daily_bars AS target
                   LEFT JOIN daily_bars AS prior ON prior.market=target.market
                       AND prior.symbol=target.symbol
                       AND prior.trade_date=(
                         SELECT MAX(p.trade_date) FROM daily_bars AS p
                         WHERE p.market=target.market AND p.symbol=target.symbol AND p.trade_date<target.trade_date
                       )
                   LEFT JOIN adj_factors AS pf ON pf.market=target.market AND pf.symbol=target.symbol
                       AND pf.trade_date=CASE WHEN target.pre_close_basis='TDX_PRIOR_RAW' THEN target.pre_close_trade_date
                                              ELSE prior.trade_date END
                   LEFT JOIN adj_factors AS tf ON tf.market=target.market AND tf.symbol=target.symbol
                       AND tf.trade_date=target.trade_date
                   WHERE target.market='A' AND target.trade_date=? ORDER BY target.symbol""", (trade_date,),
            )
            return [dict(row) for row in rows]

    def get_a_workbench_quarantines(self, trade_date: str) -> dict[str, list[str]]:
        """Read all recognized A-share isolation reasons for this exact session."""
        days = date_variants(trade_date)
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT DISTINCT symbol, reason_code FROM quarantine_events
                    WHERE market='A' AND trade_date IN ({','.join('?' for _ in days)})
                    AND reason_code IN ('TARGET_DATE_MISSING', 'INVALID_BAR:non_positive_ohlc',
                                        'NON_POSITIVE_OHLC', 'SUSPENSION_SOURCE_STALE_REVERIFY_REQUIRED')
                    ORDER BY symbol, reason_code""", days,
            )
            isolated: dict[str, list[str]] = {}
            for row in rows:
                isolated.setdefault(normalize_symbol(row["symbol"]), []).append(row["reason_code"])
            return isolated

    def upsert_adj_factors(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        sql = """
        INSERT INTO adj_factors (market, symbol, trade_date, adj_factor)
        VALUES (:market, :symbol, :trade_date, :adj_factor)
        ON CONFLICT(market, symbol, trade_date) DO UPDATE SET adj_factor=excluded.adj_factor
        """
        with self.connect() as conn:
            conn.executemany(sql, rows)
        return len(rows)

    def get_adj_factors_map(self, market: str, asof_date: str) -> dict[str, dict[str, float]]:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT symbol, trade_date, adj_factor FROM adj_factors WHERE market=? AND trade_date<=?",
                (market, asof_date),
            )
            out: dict[str, dict[str, float]] = {}
            for r in cur.fetchall():
                out.setdefault(r["symbol"], {})[r["trade_date"]] = float(r["adj_factor"])
            return out

    @staticmethod
    def _validate_qfq_scalar_writes(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
        """Reject replacing part of a KB-bound prefix with legacy bar-only updates."""
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            key = (row["market"], row["asof_date"], row["symbol"])
            groups.setdefault(key, []).append(row)

        for key, updates in groups.items():
            omitted = [sum(column not in row for column in QFQ_KB_COLUMNS) for row in updates]
            if not any(omitted):
                continue
            stored_projection = conn.execute(
                "SELECT 1 FROM qfq_bars WHERE market=? AND asof_date=? AND symbol=? "
                "AND (pre_close IS NOT NULL OR pct_chg IS NOT NULL OR user_v1_sell_signal_daily IS NOT NULL) LIMIT 1",
                key,
            ).fetchone() is not None
            incoming_projection = any(any(row.get(column) is not None for column in QFQ_KB_COLUMNS)
                                      for row in updates)
            if not (stored_projection or incoming_projection):
                continue

            stored = conn.execute(
                "SELECT trade_date, open, high, low, close, volume, amount, adj_factor "
                "FROM qfq_bars WHERE market=? AND asof_date=? AND symbol=?",
                key,
            )
            current_bars = {row["trade_date"]: tuple(row[column] for column in QFQ_BAR_COLUMNS) for row in stored}
            for row, missing in zip(updates, omitted):
                trade_date = row["trade_date"]
                bar = tuple(row[column] for column in QFQ_BAR_COLUMNS)
                legacy_row = missing == len(QFQ_KB_COLUMNS)
                if missing and (stored_projection or legacy_row) and current_bars.get(trade_date) != bar:
                    market, asof_date, symbol = key
                    raise ValueError(f"QFQ_KB_PREFIX_CONFLICT:{market}:{symbol}:{asof_date}:{trade_date}")
                current_bars[trade_date] = bar

    def upsert_qfq_bars(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        sql = """
        INSERT INTO qfq_bars (market, asof_date, symbol, trade_date, open, high, low, close, volume, amount,
                              adj_factor, pre_close, pct_chg, user_v1_sell_signal_daily)
        VALUES (:market, :asof_date, :symbol, :trade_date, :open, :high, :low, :close, :volume, :amount,
                :adj_factor, :pre_close, :pct_chg, :user_v1_sell_signal_daily)
        ON CONFLICT(market, asof_date, symbol, trade_date) DO UPDATE SET
            open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
            volume=excluded.volume, amount=excluded.amount, adj_factor=excluded.adj_factor,
            pre_close=CASE WHEN :has_pre_close THEN excluded.pre_close ELSE qfq_bars.pre_close END,
            pct_chg=CASE WHEN :has_pct_chg THEN excluded.pct_chg ELSE qfq_bars.pct_chg END,
            user_v1_sell_signal_daily=CASE WHEN :has_user_v1_sell_signal_daily THEN excluded.user_v1_sell_signal_daily
                                          ELSE qfq_bars.user_v1_sell_signal_daily END
        """
        bound_rows = (
            {**row, **{column: row.get(column) for column in QFQ_KB_COLUMNS},
             **{f"has_{column}": column in row for column in QFQ_KB_COLUMNS}}
            for row in rows
        )
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_qfq_scalar_writes(conn, rows)
            conn.executemany(sql, bound_rows)
        return len(rows)

    def record_quarantine(
        self, market: str, trade_date: str, symbol: str, reason_code: str, raw: dict[str, Any],
        *, connection: sqlite3.Connection | None = None, idempotent: bool = False,
    ) -> None:
        values = (market, trade_date, symbol, reason_code, json.dumps(raw, ensure_ascii=False, sort_keys=idempotent))
        with (nullcontext(connection) if connection is not None else self.connect()) as conn:
            if idempotent and conn.execute(
                "SELECT 1 FROM quarantine_events WHERE market=? AND trade_date=? AND symbol=? "
                "AND reason_code=? AND raw_payload=?", values,
            ).fetchone() is not None:
                return
            conn.execute(
                "INSERT INTO quarantine_events (market, trade_date, symbol, reason_code, raw_payload, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (*values, datetime.now().isoformat()),
            )

    def get_symbol_bars(
        self,
        market: str,
        symbol: str,
        table: str = "qfq_bars",
        limit: int | None = 120,
        *,
        asof_date: str | None = None,
    ) -> list[dict[str, Any]]:
        if table not in {"daily_bars", "qfq_bars"}:
            raise ValueError(f"Unsupported bar table: {table}")
        limit = -1 if limit is None else limit
        with self.connect() as conn:
            if table == "qfq_bars":
                if asof_date is None:
                    row = conn.execute(
                        "SELECT MAX(asof_date) AS mx FROM qfq_bars WHERE market=? AND symbol=?",
                        (market, symbol),
                    ).fetchone()
                    asof_date = row["mx"] if row and row["mx"] else None
                if asof_date is None:
                    return []
                cur = conn.execute(
                    "SELECT * FROM qfq_bars WHERE market=? AND asof_date=? AND symbol=? AND trade_date<=? "
                    "ORDER BY trade_date DESC LIMIT ?",
                    (market, asof_date, symbol, asof_date, limit),
                )
            else:
                if asof_date is not None:
                    cur = conn.execute(
                        "SELECT market, symbol, trade_date, open, high, low, close, volume, amount, pre_close FROM daily_bars WHERE market=? AND symbol=? AND trade_date<=? "
                        "ORDER BY trade_date DESC LIMIT ?",
                        (market, symbol, asof_date, limit),
                    )
                else:
                    cur = conn.execute(
                        "SELECT market, symbol, trade_date, open, high, low, close, volume, amount, pre_close FROM daily_bars WHERE market=? AND symbol=? ORDER BY trade_date DESC LIMIT ?",
                        (market, symbol, limit),
                    )
            rows = [dict(r) for r in cur.fetchall()]
        rows.reverse()
        return rows

    def get_date_bars(
        self,
        market: str,
        trade_date: str,
        table: str = "daily_bars",
        *,
        asof_date: str | None = None,
    ) -> list[dict[str, Any]]:
        if table not in {"daily_bars", "qfq_bars"}:
            raise ValueError(f"Unsupported bar table: {table}")
        with self.connect() as conn:
            if table == "qfq_bars":
                snap = asof_date or trade_date
                cur = conn.execute(
                    "SELECT * FROM qfq_bars WHERE market=? AND asof_date=? AND trade_date=? ORDER BY symbol",
                    (market, snap, trade_date),
                )
            else:
                cur = conn.execute(
                    "SELECT market, symbol, trade_date, open, high, low, close, volume, amount, pre_close FROM daily_bars WHERE market=? AND trade_date=? ORDER BY symbol",
                    (market, trade_date),
                )
            return [dict(r) for r in cur.fetchall()]

    def save_top200(self, trade_date: str, rows: list[dict[str, Any]]) -> int:
        with self.connect() as conn:
            conn.execute("DELETE FROM top200_daily WHERE trade_date=?", (trade_date,))
            conn.executemany(
                "INSERT INTO top200_daily (trade_date, rank, symbol, name, close, pct_chg, amount, "
                "daily_gain_rank_eligibility, historical_pit) "
                "VALUES (:trade_date, :rank, :symbol, :name, :close, :pct_chg, :amount, "
                ":daily_gain_rank_eligibility, :historical_pit)",
                rows,
            )
        return len(rows)

    def get_top200(self, trade_date: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute("SELECT * FROM top200_daily WHERE trade_date=? ORDER BY rank ASC", (trade_date,))
            return [dict(r) for r in cur.fetchall()]

    def upsert_workbench_selections(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        normalized = [
            {
                "trade_date": str(r["trade_date"]),
                "symbol": str(r["symbol"]),
                "selection_group": str(r["selection_group"]),
                "display_name": str(r.get("display_name") or r.get("name") or ""),
            }
            for r in rows
        ]
        sql = """
        INSERT INTO workbench_selections (trade_date, symbol, selection_group, display_name)
        VALUES (:trade_date, :symbol, :selection_group, :display_name)
        ON CONFLICT(trade_date, symbol) DO UPDATE SET
            selection_group=excluded.selection_group,
            display_name=CASE WHEN excluded.display_name != '' THEN excluded.display_name ELSE workbench_selections.display_name END
        """
        with self.connect() as conn:
            conn.executemany(sql, normalized)
        return len(normalized)

    def get_workbench_selections(self, trade_date: str) -> dict[str, str]:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT symbol, selection_group FROM workbench_selections WHERE trade_date=? ORDER BY symbol ASC",
                (trade_date,),
            )
            return {str(r["symbol"]): str(r["selection_group"]) for r in cur.fetchall()}

    def get_workbench_selection_names(self, trade_date: str) -> dict[str, str]:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT symbol, display_name FROM workbench_selections WHERE trade_date=? AND display_name != ''",
                (trade_date,),
            )
            return {str(r["symbol"]): str(r["display_name"]) for r in cur.fetchall()}

    def save_workbench_scores(self, trade_date: str, rows: list[dict[str, Any]]) -> int:
        with self.connect() as conn:
            conn.execute("DELETE FROM workbench_scores WHERE trade_date=?", (trade_date,))
            conn.executemany(
                "INSERT INTO workbench_scores (trade_date, symbol, selection_group, rule_version, score, action, status, detail_json) "
                "VALUES (:trade_date, :symbol, :selection_group, :rule_version, :score, :action, :status, :detail_json)",
                rows,
            )
        return len(rows)

    def get_workbench_scores(self, trade_date: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute("SELECT * FROM workbench_scores WHERE trade_date=? ORDER BY symbol ASC", (trade_date,))
            out = []
            for r in cur.fetchall():
                item = dict(r)
                item["detail"] = json.loads(item.pop("detail_json"))
                out.append(item)
            return out

    def list_workbench_dates(self) -> list[str]:
        with self.connect() as conn:
            cur = conn.execute("SELECT DISTINCT trade_date FROM workbench_scores ORDER BY trade_date DESC")
            return [str(r["trade_date"]) for r in cur.fetchall()]

    def log_task_run(self, run_id: str, trade_date: str, step: str, status: str, summary: dict[str, Any]) -> None:
        now = datetime.now().isoformat()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO task_runs (run_id, trade_date, step, status, started_at, finished_at, summary_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET status=excluded.status, finished_at=excluded.finished_at, summary_json=excluded.summary_json",
                (run_id, trade_date, step, status, now, now if status != "RUNNING" else None, json.dumps(summary, ensure_ascii=False)),
            )

    def list_task_runs(self, trade_date: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if trade_date:
                cur = conn.execute(
                    "SELECT * FROM task_runs WHERE trade_date=? ORDER BY started_at DESC",
                    (trade_date,),
                )
            else:
                cur = conn.execute("SELECT * FROM task_runs ORDER BY started_at DESC LIMIT 100")
            out = []
            for r in cur.fetchall():
                item = dict(r)
                item["summary"] = json.loads(item.pop("summary_json"))
                out.append(item)
            return out

    # --- Security Master (resolves SZ.301252 -> 同星科技) ---

    def upsert_security_master(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        normalized = [
            {
                "trade_date": str(r["trade_date"]),
                "market": str(r.get("market", "A")),
                "symbol": normalize_symbol(str(r["symbol"])),
                "display_name": str(r.get("display_name") or r.get("name") or ""),
                "industry": str(r.get("industry", "")),
                "source_ref": str(r.get("source_ref", "")),
            }
            for r in rows
            if r.get("symbol")
        ]
        sql = """
        INSERT INTO security_master (trade_date, market, symbol, display_name, industry, source_ref)
        VALUES (:trade_date, :market, :symbol, :display_name, :industry, :source_ref)
        ON CONFLICT(trade_date, market, symbol) DO UPDATE SET
            display_name=CASE WHEN excluded.display_name != '' THEN excluded.display_name ELSE security_master.display_name END,
            industry=CASE WHEN excluded.industry != '' THEN excluded.industry ELSE security_master.industry END,
            source_ref=CASE WHEN excluded.source_ref != '' THEN excluded.source_ref ELSE security_master.source_ref END
        """
        with self.connect() as conn:
            conn.executemany(sql, normalized)
        return len(normalized)

    def resolve_security_name(self, trade_date: str | None, symbol: str) -> str | None:
        canon = normalize_symbol(symbol)
        if not canon:
            return None
        with self.connect() as conn:
            if trade_date:
                variants = date_variants(trade_date)
                ph = ",".join("?" for _ in variants)
                row = conn.execute(
                    f"SELECT display_name FROM security_master WHERE trade_date IN ({ph}) AND symbol=? AND display_name != '' LIMIT 1",
                    (*variants, canon),
                ).fetchone()
                if row:
                    return str(row["display_name"])
                row = conn.execute(
                    f"SELECT name FROM top200_daily WHERE trade_date IN ({ph}) AND symbol=? AND name != '' LIMIT 1",
                    (*variants, canon),
                ).fetchone()
                if row and str(row["name"]) != canon:
                    return str(row["name"])
                row = conn.execute(
                    f"SELECT display_name FROM workbench_selections WHERE trade_date IN ({ph}) AND symbol=? AND display_name != '' LIMIT 1",
                    (*variants, canon),
                ).fetchone()
                if row:
                    return str(row["display_name"])
            row = conn.execute(
                "SELECT display_name FROM security_master WHERE symbol=? AND display_name != '' ORDER BY trade_date DESC LIMIT 1",
                (canon,),
            ).fetchone()
            if row:
                return str(row["display_name"])
            row = conn.execute(
                "SELECT name FROM top200_daily WHERE symbol=? AND name != '' ORDER BY trade_date DESC LIMIT 1",
                (canon,),
            ).fetchone()
            if row and str(row["name"]) != canon:
                return str(row["name"])
        return None

    # --- Stage Selection & Preselection Pools ---

    def upsert_stage_selections(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        normalized = [
            {
                "trade_date": str(r["trade_date"]),
                "stage": str(r["stage"]),
                "market": str(r.get("market", "A")).upper(),
                "symbol": str(r["symbol"]),
                "display_name": str(r.get("display_name") or r.get("name") or ""),
                "rank": int(r.get("rank", 0)),
                "signal_date": str(r.get("signal_date", r["trade_date"])),
                "status": str(r.get("status", "READY")),
                "execution_ref": str(r.get("execution_ref", "")),
                "payload_json": json.dumps(r.get("payload", {}), ensure_ascii=False),
            }
            for r in rows
            if r.get("symbol")
        ]
        sql = """
        INSERT INTO stage_selections (trade_date, stage, market, symbol, display_name, rank, signal_date, status, execution_ref, payload_json)
        VALUES (:trade_date, :stage, :market, :symbol, :display_name, :rank, :signal_date, :status, :execution_ref, :payload_json)
        ON CONFLICT(trade_date, stage, market, symbol) DO UPDATE SET
            display_name=CASE WHEN excluded.display_name != '' THEN excluded.display_name ELSE stage_selections.display_name END,
            rank=excluded.rank, signal_date=excluded.signal_date, status=excluded.status,
            execution_ref=excluded.execution_ref, payload_json=excluded.payload_json
        """
        with self.connect() as conn:
            conn.executemany(sql, normalized)
        return len(normalized)

    def get_stage_selections(
        self,
        trade_date: str,
        stage: str | None = None,
        market: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        variants = date_variants(trade_date)
        ph = ",".join("?" for _ in variants)
        clauses = [f"trade_date IN ({ph})"]
        params: list[Any] = list(variants)
        if stage:
            clauses.append("stage=?")
            params.append(stage)
        if market:
            clauses.append("market=?")
            params.append(market.upper())
        sql = f"SELECT * FROM stage_selections WHERE {' AND '.join(clauses)} ORDER BY rank ASC, symbol ASC"
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = []
            for r in conn.execute(sql, params).fetchall():
                item = dict(r)
                item["payload"] = json.loads(item.pop("payload_json"))
                rows.append(item)
            return rows

    def upsert_preselection_pools(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        normalized = [
            {
                "trade_date": str(r["trade_date"]),
                "pool_name": str(r["pool_name"]),
                "market": str(r.get("market", "A")).upper(),
                "symbol": str(r["symbol"]),
                "display_name": str(r.get("display_name") or r.get("name") or ""),
                "status": str(r.get("status", "READY")),
                "payload_json": json.dumps(r.get("payload", {}), ensure_ascii=False),
            }
            for r in rows
            if r.get("symbol")
        ]
        sql = """
        INSERT INTO preselection_pools (trade_date, pool_name, market, symbol, display_name, status, payload_json)
        VALUES (:trade_date, :pool_name, :market, :symbol, :display_name, :status, :payload_json)
        ON CONFLICT(trade_date, pool_name, market, symbol) DO UPDATE SET
            display_name=CASE WHEN excluded.display_name != '' THEN excluded.display_name ELSE preselection_pools.display_name END,
            status=excluded.status, payload_json=excluded.payload_json
        """
        with self.connect() as conn:
            conn.executemany(sql, normalized)
        return len(normalized)

    def get_preselection_pools(self, trade_date: str) -> list[dict[str, Any]]:
        variants = date_variants(trade_date)
        ph = ",".join("?" for _ in variants)
        with self.connect() as conn:
            cur = conn.execute(
                f"SELECT * FROM preselection_pools WHERE trade_date IN ({ph}) ORDER BY pool_name ASC, symbol ASC",
                variants,
            )
            out = []
            for r in cur.fetchall():
                item = dict(r)
                item["payload"] = json.loads(item.pop("payload_json"))
                out.append(item)
            return out

    # --- Unified Research Materials & Announcements ---

    def upsert_research_materials(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        normalized = [
            {
                "record_id": str(r["record_id"]),
                "source_type": str(r["source_type"]),
                "trade_date": str(r["trade_date"]),
                "publish_date": str(r.get("publish_date", r["trade_date"])),
                "collected_date": str(r.get("collected_date", r["trade_date"])),
                "applicable_date": str(r.get("applicable_date", r["trade_date"])),
                "market": str(r.get("market", "A")).upper(),
                "symbol": normalize_symbol(str(r.get("symbol", ""))) if r.get("symbol") else "",
                "title": str(r.get("title", "")),
                "owner_ref": str(r.get("owner_ref", "")),
                "sha256": str(r.get("sha256", "")),
                "payload_json": json.dumps(r.get("payload", {}), ensure_ascii=False),
            }
            for r in rows
            if r.get("record_id")
        ]
        sql = """
        INSERT INTO research_materials (
            record_id, source_type, trade_date, publish_date, collected_date, applicable_date,
            market, symbol, title, owner_ref, sha256, payload_json
        ) VALUES (
            :record_id, :source_type, :trade_date, :publish_date, :collected_date, :applicable_date,
            :market, :symbol, :title, :owner_ref, :sha256, :payload_json
        )
        ON CONFLICT(record_id) DO UPDATE SET
            source_type=excluded.source_type, trade_date=excluded.trade_date,
            publish_date=excluded.publish_date, collected_date=excluded.collected_date,
            applicable_date=excluded.applicable_date, market=excluded.market,
            symbol=excluded.symbol, title=excluded.title, owner_ref=excluded.owner_ref,
            sha256=excluded.sha256, payload_json=excluded.payload_json
        """
        with self.connect() as conn:
            conn.executemany(sql, normalized)
        return len(normalized)

    def query_research_materials(
        self,
        *,
        source_type: str | None = None,
        trade_date: str | None = None,
        symbol: str | None = None,
        market: str | None = None,
        q: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_type:
            clauses.append("source_type=?")
            params.append(source_type)
        if trade_date:
            clauses.append("(trade_date=? OR applicable_date=?)")
            params.extend([trade_date, trade_date])
        if symbol:
            clauses.append("symbol=?")
            params.append(normalize_symbol(symbol))
        if market:
            clauses.append("market=?")
            params.append(market.upper())
        if q:
            clauses.append("(title LIKE ? OR payload_json LIKE ? OR symbol LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM research_materials {where} ORDER BY trade_date DESC, record_id ASC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self.connect() as conn:
            out = []
            for r in conn.execute(sql, params).fetchall():
                item = dict(r)
                item["payload"] = json.loads(item.pop("payload_json"))
                out.append(item)
            return out

    def get_research_material(self, record_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM research_materials WHERE record_id=?", (record_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            return item

    def upsert_announcements(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        normalized = [
            {
                "event_id": str(r["event_id"]),
                "trade_date": str(r["trade_date"]),
                "scope_id": str(r.get("scope_id", "default")),
                "market": str(r.get("market", "A")).upper(),
                "symbol": normalize_symbol(str(r.get("symbol", ""))) if r.get("symbol") else "",
                "title": str(r.get("title", "")),
                "publish_date": str(r.get("publish_date", r["trade_date"])),
                "owner_ref": str(r.get("owner_ref", "")),
                "product_sha256": str(r.get("product_sha256", "")),
                "body_text": str(r.get("body_text", "")),
                "payload_json": json.dumps(r.get("payload", {}), ensure_ascii=False),
            }
            for r in rows
            if r.get("event_id")
        ]
        sql = """
        INSERT INTO announcements (
            event_id, trade_date, scope_id, market, symbol, title, publish_date,
            owner_ref, product_sha256, body_text, payload_json
        ) VALUES (
            :event_id, :trade_date, :scope_id, :market, :symbol, :title, :publish_date,
            :owner_ref, :product_sha256, :body_text, :payload_json
        )
        ON CONFLICT(event_id) DO UPDATE SET
            trade_date=excluded.trade_date, scope_id=excluded.scope_id, market=excluded.market,
            symbol=excluded.symbol, title=excluded.title, publish_date=excluded.publish_date,
            owner_ref=excluded.owner_ref, product_sha256=excluded.product_sha256,
            body_text=excluded.body_text, payload_json=excluded.payload_json
        """
        with self.connect() as conn:
            conn.executemany(sql, normalized)
        return len(normalized)

    def query_announcements(self, trade_date: str | None = None, scope_id: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if trade_date:
            clauses.append("trade_date=?")
            params.append(trade_date)
        if scope_id:
            clauses.append("scope_id=?")
            params.append(scope_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            out = []
            for r in conn.execute(f"SELECT * FROM announcements {where} ORDER BY trade_date DESC, event_id ASC", params).fetchall():
                item = dict(r)
                item["payload"] = json.loads(item.pop("payload_json"))
                out.append(item)
            return out

    def get_announcement(self, event_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM announcements WHERE event_id=?", (event_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            return item

    def upsert_announcement_job(
        self, job_id: str, target_date: str, state: str, *, source_job_id: str = "", payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        now = datetime.now().isoformat()
        data = payload or {}
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO announcement_jobs (job_id, target_date, state, source_job_id, created_at, updated_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at, payload_json=excluded.payload_json",
                (job_id, target_date, state, source_job_id, now, now, json.dumps(data, ensure_ascii=False)),
            )
        return {"job_id": job_id, "target_date": target_date, "state": state, "source_job_id": source_job_id, "payload": data}

    def get_announcement_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM announcement_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            return item

    def upsert_manual_collection_job(
        self, job_id: str, status: str, message: str = "", payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        now = datetime.now().isoformat()
        data = payload or {}
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO manual_collection_jobs (job_id, status, message, created_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, message=excluded.message, payload_json=excluded.payload_json",
                (job_id, status, message, now, json.dumps(data, ensure_ascii=False)),
            )
        return {"job_id": job_id, "status": status, "message": message, "created_at": now, "payload": data}

    def get_manual_collection_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM manual_collection_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            return item

    # --- Review, Manager Runs & 6-Slot Executions ---

    def save_review_record(
        self, trade_date: str, status: str, payload: dict[str, Any], *, plan_run_id: str = "default"
    ) -> dict[str, Any]:
        now = datetime.now().isoformat()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO review_records (trade_date, plan_run_id, status, payload_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(trade_date, plan_run_id) DO UPDATE SET status=excluded.status, payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (trade_date, plan_run_id, status, json.dumps(payload, ensure_ascii=False), now),
            )
        return {"trade_date": trade_date, "plan_run_id": plan_run_id, "status": status, "payload": payload, "updated_at": now}

    def get_review_record(self, trade_date: str, plan_run_id: str | None = None) -> dict[str, Any] | None:
        with self.connect() as conn:
            if plan_run_id:
                row = conn.execute(
                    "SELECT * FROM review_records WHERE trade_date=? AND plan_run_id=?",
                    (trade_date, plan_run_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM review_records WHERE trade_date=? ORDER BY updated_at DESC LIMIT 1",
                    (trade_date,),
                ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            return item

    def upsert_manager_run(self, run_id: str, trade_date: str, status: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        now = datetime.now().isoformat()
        data = payload or {}
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO manager_runs (run_id, trade_date, status, payload_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET status=excluded.status, payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (run_id, trade_date, status, json.dumps(data, ensure_ascii=False), now, now),
            )
        return {"id": run_id, "run_id": run_id, "trade_date": trade_date, "status": status, "payload": data, "updated_at": now}

    def get_manager_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM manager_runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["id"] = item["run_id"]
            item["payload"] = json.loads(item.pop("payload_json"))
            return item

    def record_slot_execution(
        self,
        trade_date: str,
        slot_id: str,
        slot_name: str,
        schedule_time: str,
        status: str,
        run_id: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trade_date = normalize_iso_date(trade_date)
        now = datetime.now().isoformat()
        execution_ref = f"v4core://{trade_date}/{slot_id}/{run_id}"
        data = detail or {}
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO slot_executions (trade_date, slot_id, slot_name, schedule_time, status, execution_ref, run_id, started_at, finished_at, detail_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(trade_date, slot_id) DO UPDATE SET "
                "status=excluded.status, execution_ref=excluded.execution_ref, run_id=excluded.run_id, "
                "finished_at=excluded.finished_at, detail_json=excluded.detail_json",
                (
                    trade_date,
                    slot_id,
                    slot_name,
                    schedule_time,
                    status,
                    execution_ref,
                    run_id,
                    now,
                    now if status != "RUNNING" else None,
                    json.dumps(data, ensure_ascii=False),
                ),
            )
        return {
            "trade_date": trade_date,
            "slot_id": slot_id,
            "slot_name": slot_name,
            "schedule_time": schedule_time,
            "status": status,
            "execution_ref": execution_ref,
            "run_id": run_id,
            "detail": data,
        }

    def get_slot_executions(self, trade_date: str) -> list[dict[str, Any]]:
        variants = date_variants(trade_date)
        ph = ",".join("?" for _ in variants)
        with self.connect() as conn:
            cur = conn.execute(
                f"SELECT * FROM slot_executions WHERE trade_date IN ({ph}) ORDER BY schedule_time ASC, slot_id ASC",
                variants,
            )
            out = []
            for r in cur.fetchall():
                item = dict(r)
                item["detail"] = json.loads(item.pop("detail_json"))
                out.append(item)
            return out

    def list_run_dates(self) -> list[str]:
        with self.connect() as conn:
            sql = """
            SELECT trade_date FROM workbench_scores
            UNION SELECT trade_date FROM daily_bars
            UNION SELECT trade_date FROM research_materials
            UNION SELECT trade_date FROM slot_executions
            UNION SELECT trade_date FROM task_runs
            ORDER BY trade_date DESC
            """
            return [str(r["trade_date"]) for r in conn.execute(sql).fetchall() if r["trade_date"]]

    @staticmethod
    def prune_old_logs(logs_dir: Path, keep_days: int = 30) -> int:
        if not logs_dir.exists():
            return 0
        cutoff = datetime.now() - timedelta(days=keep_days)
        removed = 0
        for item in logs_dir.glob("*.json"):
            if datetime.fromtimestamp(item.stat().st_mtime) < cutoff:
                item.unlink(missing_ok=True)
                removed += 1
        return removed
