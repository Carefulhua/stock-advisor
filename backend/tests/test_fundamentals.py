from datetime import date

import pandas as pd
import pytest

from app.assistant import fundamentals
from app.screener.run import latest_report_period

SECTION_KEYS = ("comment", "lhb", "dzjy", "forecast")


@pytest.fixture(autouse=True)
def _clean_cache():
    fundamentals.clear_cache()
    yield
    fundamentals.clear_cache()


def _comment_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序号": 1, "代码": "600418", "名称": "江淮汽车", "最新价": None,
                "涨跌幅": None, "换手率": 0.0, "市盈率": -31.75,
                "主力成本": 21.731388949927, "机构参与度": 0.36882,
                "综合得分": 61.09012363, "上升": -2154.0, "目前排名": 3244.0,
                "关注指数": 96.0, "交易日": "2026-10-14",
            },
            {
                "序号": 2, "代码": "600519", "名称": "贵州茅台", "最新价": 1500.0,
                "涨跌幅": 1.2, "换手率": 0.3, "市盈率": 22.5,
                "主力成本": 1450.0, "机构参与度": 0.51,
                "综合得分": 88.5, "上升": 12.0, "目前排名": 100.0,
                "关注指数": 99.0, "交易日": "2026-10-14",
            },
        ]
    )


def _lhb_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序号": 1, "代码": "600418", "名称": "江淮汽车",
                "最近上榜日": "2026-10-08", "收盘价": 24.72, "涨跌幅": -10.0109,
                "上榜次数": 3, "龙虎榜净买额": 402660474.63,
                "龙虎榜买入额": 3843251641.92, "龙虎榜卖出额": 3440591167.29,
                "龙虎榜总成交额": 7283842809.21, "买方机构次数": 0,
                "卖方机构次数": 0, "机构买入净额": 0.0, "机构买入总额": 0.0,
                "机构卖出总额": 0.0, "近1个月涨跌幅": 19.88360815,
                "近3个月涨跌幅": 6.45994832, "近6个月涨跌幅": -46.29589398,
                "近1年涨跌幅": -54.13729128,
            },
        ]
    )


def _dzjy_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序号": 1, "交易日期": "2026-08-01", "证券代码": "600418",
                "证券简称": "江淮汽车", "涨跌幅": 1.0, "收盘价": 25.0,
                "成交价": 25.1, "折溢率": 0.4, "成交量": 157000,
                "成交额": 4003500, "成交额/流通市值": 0.007,
                "买方营业部": "A营业部", "卖方营业部": "B营业部",
            },
            {
                "序号": 2, "交易日期": "2026-08-05", "证券代码": "600418",
                "证券简称": "江淮汽车", "涨跌幅": 1.8371, "收盘价": 25.5,
                "成交价": 25.5, "折溢率": 0.0, "成交量": 157000,
                "成交额": 4003500, "成交额/流通市值": 0.007188612462,
                "买方营业部": "C营业部", "卖方营业部": "D营业部",
            },
        ]
    )


def _forecast_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序号": 1, "股票代码": "600418", "股票简称": "江淮汽车",
                "预测指标": "归属于上市公司股东的净利润", "业绩变动": "旧预告",
                "预测数值": -740000000.0, "业绩变动幅度": 4.25,
                "业绩变动原因": "销量同比下滑。", "预告类型": "减亏",
                "上年同期值": -772811700.0, "公告日期": "2026-07-09",
            },
            {
                "序号": 2, "股票代码": "600418", "股票简称": "江淮汽车",
                "预测指标": "扣除非经常性损益后的净利润", "业绩变动": "新预告",
                "预测数值": -760000000.0, "业绩变动幅度": 6.10,
                "业绩变动原因": "汇兑收益同比减少3.9亿元左右。", "预告类型": "减亏",
                "上年同期值": -790000000.0, "公告日期": "2026-07-15",
            },
        ]
    )


def _patch_sections(monkeypatch, **frames: pd.DataFrame) -> dict[str, int]:
    """把四个 _fetch_xxx 替换为返回固定 frame 的桩，返回真实拉取次数计数器。"""
    defaults = {
        "comment": _comment_frame(),
        "lhb": _lhb_frame(),
        "dzjy": _dzjy_frame(),
        "forecast": _forecast_frame(),
    }
    calls = {key: 0 for key in SECTION_KEYS}

    for key, frame in {**defaults, **frames}.items():
        def make(key: str = key, frame: pd.DataFrame = frame):
            def fetch() -> pd.DataFrame:
                calls[key] += 1
                return frame

            return fetch

        monkeypatch.setattr(fundamentals, f"_fetch_{key}", make())
    return calls


def test_collect_returns_all_sections_with_real_values(monkeypatch):
    _patch_sections(monkeypatch)
    data = fundamentals.collect("600418")

    assert data["comment"]["综合得分"] == pytest.approx(61.09012363)
    assert data["comment"]["机构参与度"] == pytest.approx(0.36882)
    assert data["comment"]["市盈率"] == pytest.approx(-31.75)
    assert data["lhb"]["上榜次数"] == 3
    assert data["lhb"]["龙虎榜净买额"] == pytest.approx(402660474.63)
    assert data["lhb"]["近1个月涨跌幅"] == pytest.approx(19.88360815)
    assert data["dzjy"]["笔数"] == 2
    assert data["dzjy"]["平均折溢率"] == pytest.approx(0.2)
    assert data["dzjy"]["最近交易日期"] == "2026-08-05"
    assert data["forecast"]["预告类型"] == "减亏"
    assert data["forecast"]["预测数值"] == pytest.approx(-760000000.0)


def test_collect_normalizes_query_code(monkeypatch):
    _patch_sections(monkeypatch)
    for raw in (" 600418 ", 600418):
        data = fundamentals.collect(raw)
        assert data["comment"]["综合得分"] == pytest.approx(61.09012363)


def test_collect_pads_short_code_in_frame(monkeypatch):
    frame = _comment_frame()
    frame.loc[0, "代码"] = "418"
    _patch_sections(monkeypatch, comment=frame)

    assert fundamentals.collect("000418")["comment"]["综合得分"] == pytest.approx(61.09012363)
    assert fundamentals.collect("600418")["comment"] is None


def test_missing_stock_returns_none_per_section(monkeypatch):
    _patch_sections(monkeypatch)
    data = fundamentals.collect("000001")
    assert all(data[key] is None for key in SECTION_KEYS)


def test_single_source_failure_does_not_block_others(monkeypatch):
    _patch_sections(monkeypatch)

    def boom() -> pd.DataFrame:
        raise RuntimeError("source down")

    monkeypatch.setattr(fundamentals, "_fetch_dzjy", boom)
    data = fundamentals.collect("600418")

    assert data["dzjy"] is None
    assert data["comment"]["综合得分"] == pytest.approx(61.09012363)
    assert data["forecast"]["预告类型"] == "减亏"


def test_full_market_frames_are_fetched_once_per_day(monkeypatch):
    calls = _patch_sections(monkeypatch)
    fundamentals.collect("600418")
    fundamentals.collect("600519")
    assert all(count == 1 for count in calls.values())


def test_forecast_picks_latest_announcement(monkeypatch):
    _patch_sections(monkeypatch)
    data = fundamentals.collect("600418")

    assert data["forecast"]["公告日期"] == "2026-07-15"
    assert data["forecast"]["预测指标"] == "扣除非经常性损益后的净利润"
    assert data["forecast"]["报告期"] == latest_report_period(date.today())
    assert data["forecast"]["业绩变动原因"] == "汇兑收益同比减少3.9亿元左右。"


def test_dzjy_single_trade_aggregate(monkeypatch):
    _patch_sections(monkeypatch, dzjy=_dzjy_frame().iloc[[0]])
    data = fundamentals.collect("600418")

    assert data["dzjy"]["笔数"] == 1
    assert data["dzjy"]["成交额合计"] == pytest.approx(4003500)
    assert data["dzjy"]["平均折溢率"] == pytest.approx(0.4)
    assert data["dzjy"]["最近交易日期"] == "2026-08-01"


def test_frame_without_code_column_is_skipped(monkeypatch):
    _patch_sections(monkeypatch, comment=pd.DataFrame({"序号": [1], "名称": ["x"]}))
    data = fundamentals.collect("600418")

    assert data["comment"] is None
    assert data["lhb"]["上榜次数"] == 3
