"""多因子综合打分：横截面百分位排名 + 权重加权（纯函数，无网络、无 IO）。

只回答「同一时点谁相对更好」，输出 0-100 综合分、排名与各因子百分位，
不产出买卖判断、目标价或止损位，与 AI 解读的三条红线保持一致。

方法沿用行业内常见的截面打分：先把每个因子转成同市场内的百分位再加权，
避免量纲差异（% / 元 / 倍）直接相加；缺失值取中性 0.5 而不是 0，
否则「财报未披露」会被误判成「指标最差」。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FactorSpec:
    field: str
    weight: float
    higher_is_better: bool = True


FACTORS: tuple[FactorSpec, ...] = (
    FactorSpec("roe", 0.20),
    FactorSpec("revenue_yoy", 0.15),
    FactorSpec("net_profit_yoy", 0.15),
    FactorSpec("net_margin", 0.15),
    FactorSpec("debt_ratio", 0.15, higher_is_better=False),
    FactorSpec("gross_margin", 0.10),
    FactorSpec("cfps", 0.10),
)

SCALE = 100.0
NEUTRAL_PERCENTILE = 0.5


def default_weights() -> dict[str, float]:
    return {spec.field: spec.weight for spec in FACTORS}


def _percentile(series: pd.Series, higher_is_better: bool) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    pct = numeric.rank(pct=True, na_option="keep").fillna(NEUTRAL_PERCENTILE)
    return pct if higher_is_better else 1.0 - pct


def resolve_factors(
    available: list[str],
    weights: dict[str, float] | None = None,
) -> list[FactorSpec]:
    """挑出 df 中真实存在的因子并把权重归一化到 1；缺失的因子整体跳过。

    传入 weights 只允许覆盖内置因子的权重（方向仍按 FACTORS 的定义）。
    """
    known = {spec.field: spec for spec in FACTORS}
    if weights is None:
        candidates = dict(known)
    else:
        unknown = sorted(set(weights) - set(known))
        if unknown:
            raise KeyError(f"未知因子: {unknown}")
        candidates = {f: FactorSpec(f, w, known[f].higher_is_better) for f, w in weights.items()}

    usable = [spec for spec in candidates.values() if spec.field in available and spec.weight > 0]
    total = sum(spec.weight for spec in usable)
    if total <= 0:
        return []
    return [FactorSpec(s.field, s.weight / total, s.higher_is_better) for s in usable]


def score_universe(
    df: pd.DataFrame,
    weights: dict[str, float] | None = None,
    top: int | None = None,
) -> pd.DataFrame:
    """对全市场截面打分，返回 code/name/score/rank + 各因子百分位，按综合分降序。

    df 缺 code 列或为空时返回空表；某因子列不存在则跳过并把余下权重归一化，
    调用方可据返回的列判断实际用了哪些因子。
    """
    empty = pd.DataFrame(columns=["code", "name", "score", "rank"])
    if df.empty or "code" not in df.columns:
        return empty
    factors = resolve_factors(list(df.columns), weights)
    if not factors:
        return empty

    # 必须重排下标：调用方（如 ST 剔除）传进来的 df 常带非连续索引，
    # 而百分位按 Series 赋值是按下标对齐的，不重排会让分项错位成 NaN。
    df = df.reset_index(drop=True)
    keep = [column for column in ("code", "name") if column in df.columns]
    out = df[keep].copy()
    composite = pd.Series(0.0, index=out.index)
    for spec in factors:
        pct = _percentile(df[spec.field], spec.higher_is_better)
        out[f"pct_{spec.field}"] = pct.round(4)
        composite = composite + spec.weight * pct

    out["score"] = (composite * SCALE).round(2)
    out = out.sort_values("score", ascending=False, kind="mergesort").reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out.head(top) if top else out
