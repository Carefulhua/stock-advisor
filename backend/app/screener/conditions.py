"""条件模型与求值（纯函数：无网络、无 IO）。

条件之间为 AND；任一字段为空值（NaN/NaT/None）的行一律排除，
避免把「数据缺失」误当成「满足条件」。
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field, field_validator, model_validator

from app.screener import fields


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class Condition(BaseModel):
    field: str
    op: str
    value: float | list[float] | str | list[str]

    @field_validator("field")
    @classmethod
    def _check_field(cls, value: str) -> str:
        if not fields.is_known(value):
            raise ValueError(f"未知字段: {value}")
        return value

    @model_validator(mode="after")
    def _check_pair(self) -> "Condition":
        allowed = fields.ops_for(self.field)
        if self.op not in allowed:
            raise ValueError(f"字段 {self.field} 不支持操作符 {self.op}，可用: {list(allowed)}")
        self._check_value()
        return self

    def _check_value(self) -> None:
        kind = fields.kind_for(self.field)
        if self.op == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("between 的 value 必须是长度为 2 的数值数组")
            if not all(_is_number(item) for item in self.value):
                raise ValueError("between 的 value 必须是数值")
            low, high = float(self.value[0]), float(self.value[1])
            if low > high:
                raise ValueError("between 的下界不得大于上界")
            return
        if kind == "number":
            if not _is_number(self.value):
                raise ValueError(f"数值字段 {self.field} 的 value 必须是数值")
        elif kind == "enum":
            if not isinstance(self.value, list) or not all(isinstance(item, str) for item in self.value):
                raise ValueError(f"枚举字段 {self.field} 的 value 必须是字符串数组")
        else:
            if not isinstance(self.value, str):
                raise ValueError(f"日期字段 {self.field} 的 value 必须是 YYYY-MM-DD 字符串")


class FilterSpec(BaseModel):
    conditions: list[Condition] = Field(default_factory=list)
    sort_by: str = "net_profit_yoy"
    top: int = 100

    @field_validator("sort_by")
    @classmethod
    def _check_sort_by(cls, value: str) -> str:
        if not fields.is_known(value) or fields.kind_for(value) != "number":
            raise ValueError(f"排序字段必须是已知数值字段: {value}")
        return value

    @field_validator("top")
    @classmethod
    def _check_top(cls, value: int) -> int:
        if value < 1:
            raise ValueError("top 必须 ≥ 1")
        return value


def _compare(series: pd.Series, op: str, value: Any) -> pd.Series[bool]:
    if op == "in":
        return series.isin(list(value))
    if op == "between":
        low, high = float(value[0]), float(value[1])
        return (series >= low) & (series <= high)
    if pd.api.types.is_datetime64_any_dtype(series):
        bound = pd.Timestamp(value)
        return series >= bound if op == "gte" else series <= bound
    column = pd.to_numeric(series, errors="coerce")
    if op == "gte":
        return column >= float(value)
    if op == "gt":
        return column > float(value)
    if op == "lte":
        return column <= float(value)
    if op == "lt":
        return column < float(value)
    raise ValueError(f"未知操作符: {op}")


def evaluate(df: pd.DataFrame, conditions: list[Condition]) -> pd.DataFrame:
    result = df
    for condition in conditions:
        if condition.field not in result.columns:
            return result.iloc[0:0]
        series = result[condition.field]
        if fields.kind_for(condition.field) == "date":
            series = pd.to_datetime(series, errors="coerce")
        elif fields.kind_for(condition.field) == "number":
            series = pd.to_numeric(series, errors="coerce")
        else:
            series = series.where(series.notna())
        mask = _compare(series, condition.op, condition.value)
        mask = mask.fillna(False).astype(bool)
        result = result.loc[mask]
    return result.reset_index(drop=True)