"""报告补充数据源：资金面与事件面。

龙虎榜统计、大宗交易、业绩预告、千股千评均为「全市场单次拉取 + 按 code 过滤」，
与 screener.snapshot 的全市场快照同一模式，不按个股逐只请求。
"""
from __future__ import annotations

import logging
import re
from datetime import date

import akshare as ak
import pandas as pd

from app.data.fetchers import _with_retry
from app.screener.run import latest_report_period

logger = logging.getLogger(__name__)

DZJY_WINDOW_DAYS = 90

CODE_COLUMNS = ("股票代码", "证券代码", "代码")

_CACHE: dict[str, tuple[str, pd.DataFrame]] = {}


def clear_cache() -> None:
    _CACHE.clear()


def _cached(key: str, fetch) -> pd.DataFrame:
    """全市场数据按自然日缓存：同日为不同个股生成报告时只拉一次。"""
    today = date.today().isoformat()
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == today:
        return hit[1]
    frame = fetch()
    _CACHE[key] = (today, frame)
    return frame


def _rows_for(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    column = next((c for c in CODE_COLUMNS if c in frame.columns), None)
    if column is None:
        raise ValueError(f"no code column in {list(frame.columns)[:5]}")
    return frame[frame[column].astype(str).str.zfill(6) == code]


def _num(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _text(value: object) -> str:
    return "" if value is None or value != value else str(value).strip()


def collect(code: str) -> dict:
    """按 code 采集补充数据源；单个来源失败只记日志，不阻塞其余来源。

    前四个源是全市场单次拉取后按 code 过滤；business 是逐股接口，需单独请求。
    """
    normalized = str(code).strip().zfill(6)
    data: dict[str, object] = {}
    for key, loader in (
        ("comment", _comment_of),
        ("lhb", _lhb_of),
        ("dzjy", _dzjy_of),
        ("forecast", _forecast_of),
        ("business", _business_of),
    ):
        try:
            data[key] = loader(normalized)
        except Exception as exc:  # noqa: BLE001 - 数据源异常类型不可控
            logger.warning("fundamentals %s 拉取失败(%s): %s", key, normalized, exc)
            data[key] = None
    return data


def _fetch_comment() -> pd.DataFrame:
    return _with_retry(ak.stock_comment_em)


def _comment_of(code: str) -> dict | None:
    rows = _rows_for(_cached("comment", _fetch_comment), code)
    if rows.empty:
        return None
    row = rows.iloc[-1]
    return {
        "综合得分": _num(row.get("综合得分")),
        "机构参与度": _num(row.get("机构参与度")),
        "主力成本": _num(row.get("主力成本")),
        "关注指数": _num(row.get("关注指数")),
        "目前排名": _num(row.get("目前排名")),
        "市盈率": _num(row.get("市盈率")),
    }


def _fetch_lhb() -> pd.DataFrame:
    return _with_retry(ak.stock_lhb_stock_statistic_em, symbol="近一月")


def _lhb_of(code: str) -> dict | None:
    rows = _rows_for(_cached("lhb", _fetch_lhb), code)
    if rows.empty:
        return None
    row = rows.iloc[-1]
    return {
        "最近上榜日": _text(row.get("最近上榜日")),
        "上榜次数": _num(row.get("上榜次数")),
        "龙虎榜净买额": _num(row.get("龙虎榜净买额")),
        "机构买入净额": _num(row.get("机构买入净额")),
        "近1个月涨跌幅": _num(row.get("近1个月涨跌幅")),
    }


def _fetch_dzjy() -> pd.DataFrame:
    end = date.today()
    start = end.fromordinal(end.toordinal() - DZJY_WINDOW_DAYS)
    return _with_retry(
        ak.stock_dzjy_mrmx,
        symbol="A股",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )


def _dzjy_of(code: str) -> dict | None:
    rows = _rows_for(_cached("dzjy", _fetch_dzjy), code)
    if rows.empty:
        return None
    rows = rows.sort_values("交易日期")
    latest = rows.iloc[-1]
    amounts = rows["成交额"].map(_num).dropna()
    discounts = rows["折溢率"].map(_num).dropna()
    return {
        "笔数": len(rows),
        "成交额合计": float(amounts.sum()) if not amounts.empty else None,
        "平均折溢率": float(discounts.mean()) if not discounts.empty else None,
        "最近交易日期": _text(latest.get("交易日期")),
        "最近成交价": _num(latest.get("成交价")),
        "最近收盘价": _num(latest.get("收盘价")),
        "最近买方营业部": _text(latest.get("买方营业部")),
        "最近卖方营业部": _text(latest.get("卖方营业部")),
    }


def _fetch_forecast() -> pd.DataFrame:
    return _with_retry(ak.stock_yjyg_em, date=latest_report_period(date.today()))


HEADLINE_METRIC = "归属于上市公司股东的净利润"


def _forecast_of(code: str) -> dict | None:
    rows = _rows_for(_cached("forecast", _fetch_forecast), code)
    if rows.empty:
        return None
    frame = rows.copy()
    frame["_公告日"] = pd.to_datetime(frame["公告日期"], errors="coerce")
    # 同一公告日常同时披露归母与扣非两条口径，第二次排序键让归母这条排在后端被选中
    frame["_头条口径"] = frame["预测指标"].astype(str).eq(HEADLINE_METRIC)
    row = frame.sort_values(["_公告日", "_头条口径"]).iloc[-1]
    return {
        "报告期": latest_report_period(date.today()),
        "预测指标": _text(row.get("预测指标")),
        "预告类型": _text(row.get("预告类型")),
        "业绩变动幅度": _num(row.get("业绩变动幅度")),
        "预测数值": _num(row.get("预测数值")),
        "上年同期值": _num(row.get("上年同期值")),
        "业绩变动原因": _text(row.get("业绩变动原因")),
        "公告日期": _text(row.get("公告日期")),
    }


def _core_scope(scope: str) -> str:
    """取工商经营范围的核心句，去掉「依法须经批准的项目…」这类 boilerplate。"""
    if not scope:
        return ""
    head = re.split(r"[。；]\s*（?依法", scope, maxsplit=1)[0]
    head = head.split("一般项目")[0]
    head = head.strip(" ；;。")
    return head if len(head) >= 8 else scope[:120]


def _business_of(code: str) -> dict | None:
    """公司主营业务与经营范围（ths 逐股接口，非全市场）。"""
    rows = _with_retry(ak.stock_zyjs_ths, symbol=code)
    if rows.empty:
        return None
    row = rows.iloc[0]
    business = _text(row.get("主营业务"))
    scope = _text(row.get("经营范围"))
    products = _text(row.get("产品名称")) or _text(row.get("产品类型"))
    return {
        "主营业务": business,
        "产品": products,
        "经营范围": _core_scope(scope),
    }
