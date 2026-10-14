"""字段目录：筛选可用维度的单一事实源（纯数据，无 IO）。

前端动态渲染表单与 LLM 解析 prompt 都以本目录为准，新增维度只需在此追加。
"""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

NUMERIC_OPS: tuple[str, ...] = ("gte", "gt", "lte", "lt", "between")
DATE_OPS: tuple[str, ...] = ("gte", "lte")
ENUM_OPS: tuple[str, ...] = ("in",)

OP_LABELS: dict[str, str] = {
    "gte": "≥",
    "gt": ">",
    "lte": "≤",
    "lt": "<",
    "between": "介于",
    "in": "属于",
}


@dataclass
class FieldSpec:
    field: str
    label: str
    unit: str
    kind: str  # number | enum | date
    ops: tuple[str, ...]
    options: list[str] = dataclass_field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "label": self.label,
            "unit": self.unit,
            "kind": self.kind,
            "ops": list(self.ops),
            "options": list(self.options),
            "op_labels": [OP_LABELS[op] for op in self.ops],
        }


FIELDS: list[FieldSpec] = [
    FieldSpec("pe_ttm", "市盈率TTM", "倍", "number", NUMERIC_OPS),
    FieldSpec("pn", "市净率", "倍", "number", NUMERIC_OPS),
    FieldSpec("turnover", "成交额", "元", "number", NUMERIC_OPS),
    FieldSpec("ltsz", "流通市值", "元", "number", NUMERIC_OPS),
    FieldSpec("zsz", "总市值", "元", "number", NUMERIC_OPS),
    FieldSpec("hsl", "换手率", "%", "number", NUMERIC_OPS),
    FieldSpec("lb", "量比", "倍", "number", NUMERIC_OPS),
    FieldSpec("zdf_y", "年初至今涨幅", "%", "number", NUMERIC_OPS),
    FieldSpec("zdf_d20", "近20日涨幅", "%", "number", NUMERIC_OPS),
    FieldSpec("zdf_d60", "近60日涨幅", "%", "number", NUMERIC_OPS),
    FieldSpec("zljlr", "主力净流入", "元", "number", NUMERIC_OPS),
    FieldSpec("eps", "每股收益", "元", "number", NUMERIC_OPS),
    FieldSpec("cfps", "每股经营现金流", "元", "number", NUMERIC_OPS),
    FieldSpec("revenue_yoy", "营收同比", "%", "number", NUMERIC_OPS),
    FieldSpec("net_profit_yoy", "净利润同比", "%", "number", NUMERIC_OPS),
    FieldSpec("net_profit", "净利润", "元", "number", NUMERIC_OPS),
    FieldSpec("roe", "净资产收益率", "%", "number", NUMERIC_OPS),
    FieldSpec("gross_margin", "销售毛利率", "%", "number", NUMERIC_OPS),
    FieldSpec("debt_ratio", "资产负债率", "%", "number", NUMERIC_OPS),
    FieldSpec("net_margin", "销售净利率", "%", "number", NUMERIC_OPS),
    FieldSpec("revenue_qoq", "营收环比", "%", "number", NUMERIC_OPS),
    FieldSpec("net_profit_qoq", "净利润环比", "%", "number", NUMERIC_OPS),
    FieldSpec("industry", "所处行业", "分类", "enum", ENUM_OPS),
    FieldSpec("list_date", "上市日期", "年-月-日", "date", DATE_OPS),
]

_BY_NAME: dict[str, FieldSpec] = {item.field: item for item in FIELDS}


def by_name(field: str) -> FieldSpec:
    if field not in _BY_NAME:
        raise KeyError(field)
    return _BY_NAME[field]


def is_known(field: str) -> bool:
    return field in _BY_NAME


def ops_for(field: str) -> tuple[str, ...]:
    return by_name(field).ops


def kind_for(field: str) -> str:
    return by_name(field).kind


def set_industry_options(options: list[str]) -> None:
    """行业取值来自业绩报表的动态列，运行时填充后供前端多选与解析 prompt 使用。"""
    by_name("industry").options = list(options)


def catalog() -> list[dict[str, object]]:
    return [item.to_dict() for item in FIELDS]


def numeric_fields() -> list[FieldSpec]:
    return [item for item in FIELDS if item.kind == "number"]