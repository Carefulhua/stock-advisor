"""存储层测试: 不依赖网络, 使用临时目录。"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.core import config
from app.data import storage


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    quotes_dir = tmp_path / "quotes"
    fin_dir = tmp_path / "financials"
    db_path = tmp_path / "test.db"
    quotes_dir.mkdir()
    fin_dir.mkdir()
    monkeypatch.setattr(config, "QUOTES_DIR", quotes_dir)
    monkeypatch.setattr(config, "FINANCIALS_DIR", fin_dir)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    return db_path


def _make_quotes(dates: list[str], code: str = "000001") -> pd.DataFrame:
    rows = [
        {
            "date": d, "code": code, "open": 10.0, "close": 10.5,
            "high": 10.8, "low": 9.9, "volume": 1000, "amount": 10500.0,
            "amplitude": 1.0, "pct_chg": 0.5, "chg": 0.05, "turnover": 0.3,
        }
        for d in dates
    ]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def test_upsert_and_list_stocks(tmp_env):
    conn = storage.get_conn()
    df = pd.DataFrame({"code": ["1", "600519"], "name": ["平安银行", "贵州茅台"]})
    n = storage.upsert_stocks(conn, df)
    assert n == 2
    out = storage.list_stocks(conn)
    assert out.iloc[0]["code"] == "000001"  # zfill(6)
    # 重复 upsert 不报错且更新 name
    storage.upsert_stocks(conn, pd.DataFrame({"code": ["1"], "name": ["新名字"]}))
    out = storage.list_stocks(conn)
    assert len(out) == 2
    assert out[out["code"] == "000001"]["name"].iloc[0] == "新名字"
    conn.close()


def test_append_quotes_dedupe_and_increment(tmp_env):
    storage.append_quotes("000001", _make_quotes(["2025-01-02", "2025-01-03"]))
    # 重复日期 + 新日期: 去重且新数据覆盖
    n = storage.append_quotes(
        "000001",
        _make_quotes(["2025-01-03", "2025-01-06"]),
    )
    assert n == 3
    out = storage.read_quotes("000001")
    assert len(out) == 3
    assert list(out["date"].dt.strftime("%Y-%m-%d")) == [
        "2025-01-02", "2025-01-03", "2025-01-06",
    ]


def test_last_quote_date(tmp_env):
    assert storage.last_quote_date("000001") is None
    storage.append_quotes("000001", _make_quotes(["2025-01-02", "2025-01-03"]))
    assert storage.last_quote_date("000001") == date(2025, 1, 3)


def test_append_quotes_empty(tmp_env):
    n = storage.append_quotes("000001", pd.DataFrame())
    assert n == 0
    empty = storage.read_quotes("000001")
    assert empty.empty


def test_append_quotes_missing_column_raises(tmp_env):
    bad = _make_quotes(["2025-01-02"]).drop(columns=["turnover"])
    with pytest.raises(ValueError, match="missing columns"):
        storage.append_quotes("000001", bad)


def test_read_quotes_date_filter(tmp_env):
    storage.append_quotes(
        "000001",
        _make_quotes(["2025-01-02", "2025-01-03", "2025-01-06"]),
    )
    out = storage.read_quotes("000001", start="2025-01-03", end="2025-01-05")
    assert len(out) == 1


def test_financials_roundtrip(tmp_env):
    df = pd.DataFrame({"日期": ["2024-12-31"], "摊薄每股收益(元)": [1.5]})
    n = storage.write_financials("000001", df)
    assert n == 1
    out = storage.read_financials("000001")
    assert out["摊薄每股收益(元)"].iloc[0] == 1.5
    # 覆盖写
    storage.write_financials("000001", df.head(0))
    assert storage.read_financials("000001").empty


def test_mark_sync_state(tmp_env):
    conn = storage.get_conn()
    storage.upsert_stocks(conn, pd.DataFrame({"code": ["000001"], "name": ["x"]}))
    storage.mark_quotes_synced(conn, "000001")
    storage.mark_financials_synced(conn, "000001")
    row = pd.read_sql_query("SELECT * FROM stocks WHERE code='000001'", conn)
    assert row["quotes_synced_at"].notna().all()
    assert row["financials_synced_at"].notna().all()
    conn.close()


def test_chat_history_roundtrip(tmp_env):
    conn = storage.get_conn()
    n = storage.append_chat_messages(
        conn,
        "300456",
        [
            {"role": "user", "content": "这只怎么样"},
            {"role": "assistant", "content": "偏强震荡"},
            {"role": "user", "content": ""},  # 空内容忽略
            {"role": "system", "content": "x"},  # 非法角色忽略
        ],
    )
    assert n == 2
    msgs = storage.read_chat_messages(conn, "300456")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "这只怎么样"
    assert msgs[0]["created_at"]
    # 其他股票互不干扰
    assert storage.read_chat_messages(conn, "000001") == []
    conn.close()


def test_chat_history_trims_oldest(tmp_env):
    conn = storage.get_conn()
    for i in range(storage.CHAT_STORE_LIMIT + 10):
        storage.append_chat_messages(
            conn, "000001", [{"role": "user", "content": f"q{i}"}]
        )
    msgs = storage.read_chat_messages(conn, "000001", limit=1000)
    assert len(msgs) == storage.CHAT_STORE_LIMIT
    assert msgs[0]["content"] == "q10"  # 最旧10条被裁剪
    conn.close()


def test_chat_read_limit(tmp_env):
    conn = storage.get_conn()
    storage.append_chat_messages(
        conn,
        "000002",
        [{"role": "user", "content": f"m{i}"} for i in range(5)],
    )
    msgs = storage.read_chat_messages(conn, "000002", limit=3)
    assert [m["content"] for m in msgs] == ["m2", "m3", "m4"]
    conn.close()
