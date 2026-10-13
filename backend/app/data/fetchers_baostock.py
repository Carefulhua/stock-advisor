"""baostock 日线采集 (批量回填主数据源, 无限频问题)。

单位约定: volume=股, amount=元, turnover/pct_chg=%, 与 akshare 路径对齐
(akshare/东财 volume 单位为手, fetch_daily 中已 x100 归一化)。
"""
from __future__ import annotations

import logging
import socket
from datetime import date, datetime, timedelta

import pandas as pd
import baostock as bs
import baostock.common.contants as cons

logger = logging.getLogger(__name__)

# baostock SDK 的 recv 无超时, 服务器停顿会导致进程永久卡死;
# 只影响新建 socket, urllib3/requests 均显式传 timeout 不受影响
socket.setdefaulttimeout(30)

_BS_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "pctChg,turn,tradestatus"
)
_ERR_RECV = cons.BSERR_RECVSOCK_FAIL
_CHUNK_YEARS = 4

_LOGIN = False


def to_bs_code(code: str) -> str:
    if code.startswith("6"):
        return f"sh.{code}"
    if code.startswith(("0", "3")):
        return f"sz.{code}"
    raise ValueError(f"baostock unsupported market for code: {code}")


def is_supported(code: str) -> bool:
    return code.startswith(("0", "3", "6"))


def _login() -> None:
    global _LOGIN
    if _LOGIN:
        return
    rs = bs.login()
    if rs.error_code != "0":
        raise RuntimeError(f"baostock login failed: {rs.error_msg}")
    _LOGIN = True


def _reconnect() -> None:
    """关闭旧连接并重新登录 (baostock 单会话单 socket, 断连后协议状态失效)。"""
    global _LOGIN
    import baostock.common.context as ctx

    old = getattr(ctx, "default_socket", None)
    if old is not None:
        try:
            old.close()
        except OSError:
            pass
        setattr(ctx, "default_socket", None)
    _LOGIN = False
    _login()


def logout() -> None:
    global _LOGIN
    if _LOGIN:
        bs.logout()
        _LOGIN = False


def _fmt(date_ymmdd: str) -> str:
    return f"{date_ymmdd[:4]}-{date_ymmdd[4:6]}-{date_ymmdd[6:]}"


def _chunks(start_ymmdd: str, end_ymmdd: str) -> list[tuple[str, str]]:
    """按 4 个自然年切分区间: 每块 ≤~970 个交易日 < SDK 单页 2000 行,
    避免走 resultset.next() 的隐式翻页路径 (该路径网络失败时静默截断)。
    """
    start = datetime.strptime(start_ymmdd, "%Y%m%d").date()
    end = datetime.strptime(end_ymmdd, "%Y%m%d").date()
    out: list[tuple[str, str]] = []
    while start <= end:
        chunk_end = min(end, date(start.year + _CHUNK_YEARS, 1, 1) - timedelta(days=1))
        out.append((start.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        start = chunk_end + timedelta(days=1)
    return out


def _query(code: str, start_date: str, end_date: str):
    """查询一个分块; 网络接收失败(10002007)时重连后重试一次。"""
    _login()
    rs = bs.query_history_k_data_plus(
        to_bs_code(code),
        _BS_FIELDS,
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="2",
    )
    if rs.error_code == _ERR_RECV:
        logger.warning(
            "baostock recv fail for %s, reconnecting: %s", code, rs.error_msg
        )
        _reconnect()
        rs = bs.query_history_k_data_plus(
            to_bs_code(code),
            _BS_FIELDS,
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",
        )
    return rs


def fetch_daily(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """前复权日线, start/end 为 YYYYMMDD。停牌日(tradestatus!=1)剔除。"""
    cols = _BS_FIELDS.split(",")
    parts: list[pd.DataFrame] = []
    for chunk_start, chunk_end in _chunks(start_date, end_date):
        rs = _query(code, _fmt(chunk_start), _fmt(chunk_end))
        if rs.error_code != "0":
            raise RuntimeError(f"baostock query failed for {code}: {rs.error_msg}")
        rows: list[list[str]] = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if rows:
            parts.append(pd.DataFrame(rows, columns=cols))

    if not parts:
        return pd.DataFrame(columns=_columns())

    df = pd.concat(parts, ignore_index=True)
    df = df[df["tradestatus"] == "1"].copy()
    if df.empty:
        return pd.DataFrame(columns=_columns())

    for col in ("open", "high", "low", "close", "preclose", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "preclose"])

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"]),
            "code": code,
            "open": df["open"],
            "close": df["close"],
            "high": df["high"],
            "low": df["low"],
            "volume": df["volume"].astype("int64"),
            "amount": df["amount"],
            "amplitude": (df["high"] - df["low"]) / df["preclose"] * 100,
            "pct_chg": pd.to_numeric(df["pctChg"], errors="coerce"),
            "chg": df["close"] - df["preclose"],
            "turnover": pd.to_numeric(df["turn"], errors="coerce"),
        }
    )
    return out[_columns()].reset_index(drop=True)


def _columns() -> list[str]:
    from app.data.storage import QUOTE_COLUMNS

    return QUOTE_COLUMNS
