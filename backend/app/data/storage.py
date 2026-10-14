"""SQLite(结构化) + Parquet(行情/财务) 存储层。

约定:
- stocks 表: 股票列表 + 每只股票的同步状态
- data/quotes/{code}.parquet: 日线行情, 增量追加, 按 date 去重
- data/financials/{code}.parquet: 财务指标(中文列名), 全量覆盖
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, date
from pathlib import Path

import pandas as pd

from app.core import config

QUOTE_COLUMNS = [
    "date", "code", "open", "close", "high", "low",
    "volume", "amount", "amplitude", "pct_chg", "chg", "turnover",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    quotes_synced_at TEXT,
    financials_synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS watchlist (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    score REAL NOT NULL,
    rank INTEGER NOT NULL,
    selected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS favorites (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_history_code ON chat_history(code, id);
"""

CHAT_STORE_LIMIT = 200  # 每只股票最多保留的对话条数（滚动裁剪最旧）


def get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    return conn


def upsert_stocks(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    """写入股票列表, 返回记录数。"""
    rows = [(str(r["code"]).zfill(6), str(r["name"])) for r in df.to_dict("records")]
    conn.executemany(
        "INSERT INTO stocks(code, name) VALUES(?, ?) "
        "ON CONFLICT(code) DO UPDATE SET name=excluded.name",
        rows,
    )
    conn.commit()
    return len(rows)


def list_stocks(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT code, name FROM stocks ORDER BY code", conn)


def mark_quotes_synced(conn: sqlite3.Connection, code: str, at: datetime | None = None) -> None:
    ts = (at or datetime.now()).isoformat(timespec="seconds")
    conn.execute("UPDATE stocks SET quotes_synced_at=? WHERE code=?", (ts, code))
    conn.commit()


def mark_financials_synced(conn: sqlite3.Connection, code: str, at: datetime | None = None) -> None:
    ts = (at or datetime.now()).isoformat(timespec="seconds")
    conn.execute("UPDATE stocks SET financials_synced_at=? WHERE code=?", (ts, code))
    conn.commit()


def _quotes_path(code: str, quotes_dir: Path | None = None) -> Path:
    return (quotes_dir or config.QUOTES_DIR) / f"{code}.parquet"


def last_quote_date(code: str, quotes_dir: Path | None = None) -> date | None:
    """本地已存该股票的最新交易日, 无数据返回 None。"""
    path = _quotes_path(code, quotes_dir)
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=["date"])
    if df.empty:
        return None
    return pd.to_datetime(df["date"]).max().date()


def append_quotes(
    code: str,
    new: pd.DataFrame,
    quotes_dir: Path | None = None,
) -> int:
    """增量追加日线行情: 与本地数据按 date 去重, 新数据覆盖旧数据。

    返回合并后的总行数。
    """
    if new.empty:
        path = _quotes_path(code, quotes_dir)
        return len(pd.read_parquet(path)) if path.exists() else 0

    df = new.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["code"] = code
    missing = [c for c in QUOTE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"quotes missing columns: {missing}")
    df = df[QUOTE_COLUMNS]

    path = _quotes_path(code, quotes_dir)
    if path.exists():
        old = pd.read_parquet(path)
        old["date"] = pd.to_datetime(old["date"])
        df = (
            pd.concat([old, df], ignore_index=True)
            .drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return len(df)


def read_quotes(
    code: str,
    start: str | None = None,
    end: str | None = None,
    quotes_dir: Path | None = None,
) -> pd.DataFrame:
    path = _quotes_path(code, quotes_dir)
    if not path.exists():
        return pd.DataFrame(columns=QUOTE_COLUMNS)
    df = pd.read_parquet(path)
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    if end:
        df = df[df["date"] <= pd.Timestamp(end)]
    return df.reset_index(drop=True)


def write_financials(
    code: str,
    df: pd.DataFrame,
    financials_dir: Path | None = None,
) -> int:
    """财务指标全量覆盖写入(每次拉取即最新全量)。"""
    path = (financials_dir or config.FINANCIALS_DIR) / f"{code}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return len(df)


def read_financials(code: str, financials_dir: Path | None = None) -> pd.DataFrame:
    path = (financials_dir or config.FINANCIALS_DIR) / f"{code}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _normalize_code(raw: object) -> str | None:
    code = str(raw).strip().zfill(6)
    if len(code) != 6 or not code.isdigit():
        return None
    return code


def add_favorites(
    conn: sqlite3.Connection,
    codes_and_names: list[tuple[str, str]],
    added_at: str | None = None,
) -> tuple[int, int]:
    """批量添加手工自选股, 返回 (新增数, 跳过数)。code 非6位数字视为非法并跳过。"""
    ts = added_at or datetime.now().isoformat(timespec="seconds")
    added = 0
    skipped = 0
    with conn:
        for raw_code, name in codes_and_names:
            code = _normalize_code(raw_code)
            if code is None:
                skipped += 1
                continue
            cursor = conn.execute(
                "INSERT OR IGNORE INTO favorites(code, name, added_at) VALUES(?, ?, ?)",
                (code, str(name), ts),
            )
            if cursor.rowcount:
                added += 1
            else:
                skipped += 1
    return added, skipped


def remove_favorite(conn: sqlite3.Connection, code: str) -> bool:
    normalized = _normalize_code(code)
    if normalized is None:
        return False
    with conn:
        cursor = conn.execute("DELETE FROM favorites WHERE code = ?", (normalized,))
    return bool(cursor.rowcount)


def read_favorites(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT code, name, added_at FROM favorites ORDER BY added_at, code",
        conn,
    )


def replace_watchlist(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    selected_at: datetime | None = None,
) -> int:
    """整表替换自选池, 返回写入条数。"""
    return replace_watchlist_by_codes(conn, df, selected_at)


def replace_watchlist_by_codes(
    conn: sqlite3.Connection,
    rows: pd.DataFrame,
    selected_at: datetime | None = None,
) -> int:
    """按 rank 升序整表替换自选池, 缺失 score 记0, 返回写入条数。"""
    ts = (selected_at or datetime.now()).isoformat(timespec="seconds")
    prepared = []
    for record in sorted(rows.to_dict("records"), key=lambda r: int(r["rank"])):
        code = _normalize_code(record["code"])
        if code is None:
            continue
        prepared.append(
            (code, str(record["name"]), float(record.get("score") or 0.0), int(record["rank"]), ts)
        )
    with conn:
        conn.execute("DELETE FROM watchlist")
        conn.executemany(
            "INSERT INTO watchlist(code, name, score, rank, selected_at) VALUES(?, ?, ?, ?, ?)",
            prepared,
        )
    return len(prepared)


def read_watchlist(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT code, name, score, rank, selected_at FROM watchlist ORDER BY rank",
        conn,
    )


def append_chat_messages(conn: sqlite3.Connection, code: str, messages: list[dict]) -> int:
    """追加对话记录, 超出 CHAT_STORE_LIMIT 裁剪最旧。返回写入条数。"""
    normalized = _normalize_code(code)
    if normalized is None or not messages:
        return 0
    rows = [
        (normalized, str(m["role"]), str(m["content"]))
        for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    if not rows:
        return 0
    with conn:
        conn.executemany(
            "INSERT INTO chat_history(code, role, content) VALUES(?, ?, ?)", rows
        )
        conn.execute(
            "DELETE FROM chat_history WHERE code = ? AND id NOT IN ("
            "SELECT id FROM chat_history WHERE code = ? ORDER BY id DESC LIMIT ?)",
            (normalized, normalized, CHAT_STORE_LIMIT),
        )
    return len(rows)


def read_chat_messages(conn: sqlite3.Connection, code: str, limit: int = 50) -> list[dict]:
    """读取某只股票最近 limit 条对话, 升序返回。"""
    normalized = _normalize_code(code)
    if normalized is None:
        return []
    df = pd.read_sql_query(
        "SELECT role, content, created_at FROM chat_history "
        "WHERE code = ? ORDER BY id DESC LIMIT ?",
        conn,
        params=(normalized, limit),
    )
    return df.iloc[::-1].to_dict("records")
