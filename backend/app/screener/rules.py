"""硬过滤与打分（纯函数：无网络、无 IO）。"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def apply_hard_filters(
    df: pd.DataFrame,
    *,
    as_of: date,
    min_float_mv: float,
    min_amount: float,
    min_listing_years: int,
) -> pd.DataFrame:
    """剔除 ST/非沪深主板创业板/停牌/次新/流动性不足; 上市日期缺失一律剔除。"""
    cutoff = pd.Timestamp(as_of - timedelta(days=365 * min_listing_years))
    mask = (
        ~df["name"].str.upper().str.contains("ST", na=False)
        & df["code"].str[0].isin(["0", "3", "6"])
        & (df["amount"] > 0)
        & df["list_date"].notna()
        & (df["list_date"] <= cutoff)
        & ((df["float_mv"] >= min_float_mv) | (df["amount"] >= min_amount))
    )
    return df.loc[mask].reset_index(drop=True)


def _minmax(s: pd.Series) -> pd.Series:
    """min-max 归一到 [0,1]; 全空或常数列全记 0。"""
    lo, hi = s.min(), s.max()
    if pd.isna(lo) or pd.isna(hi) or hi == lo:
        return pd.Series(0.0, index=s.index)
    return (s - lo) / (hi - lo)


def score_stocks(
    df: pd.DataFrame,
    *,
    weight_amount: float,
    weight_pe: float,
    weight_growth: float,
) -> pd.DataFrame:
    """三项 min-max 归一加权得 0–100 分; PE≤0 记 0, 增速缺失记 0, PE 越低越好。"""
    out = df.copy()
    out["score_amount"] = _minmax(out["amount"])
    out["score_pe"] = _minmax(-out["pe"].where(out["pe"] > 0)).fillna(0.0)
    out["score_growth"] = _minmax(out["profit_yoy"]).fillna(0.0)
    out["score"] = 100 * (
        weight_amount * out["score_amount"]
        + weight_pe * out["score_pe"]
        + weight_growth * out["score_growth"]
    )
    return out


def select_top(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """按 score 降序取前 n 并赋 rank; 候选不足报错。"""
    if len(df) < n:
        raise ValueError(f"候选不足: {len(df)} < {n}")
    out = df.sort_values("score", ascending=False, kind="stable").head(n).copy()
    out["rank"] = range(1, n + 1)
    return out.reset_index(drop=True)
