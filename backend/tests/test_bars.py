import pandas as pd
import pytest

from app.analysis.bars import BAR_PERIODS, resample_bars


def _daily() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-01-05",
                    "2026-01-06",
                    "2026-01-07",
                    "2026-01-08",
                    "2026-02-02",
                    "2026-02-03",
                    "2026-05-06",
                ]
            ),
            "open": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0],
            "high": [12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0],
            "low": [9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
            "close": [11.0, 12.0, 11.0, 14.0, 15.0, 14.0, 17.0],
            "volume": [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0],
            "amount": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
        }
    )


def test_day_returns_input_unchanged():
    df = _daily()
    assert resample_bars(df, "day").equals(df)


def test_week_groups_by_natural_week_with_last_trading_day():
    out = resample_bars(_daily(), "week")
    assert list(out["date"].dt.strftime("%Y-%m-%d")) == ["2026-01-08", "2026-02-03", "2026-05-06"]
    assert list(out["open"]) == [10.0, 14.0, 16.0]
    assert list(out["high"]) == [15.0, 17.0, 18.0]
    assert list(out["low"]) == [9.0, 13.0, 15.0]
    assert list(out["close"]) == [14.0, 14.0, 17.0]
    assert list(out["volume"]) == [1000.0, 1100.0, 700.0]
    assert list(out["amount"]) == [10.0, 11.0, 7.0]


def test_month_and_year_aggregate_correctly():
    monthly = resample_bars(_daily(), "month")
    assert list(monthly["date"].dt.strftime("%Y-%m-%d")) == ["2026-01-08", "2026-02-03", "2026-05-06"]
    yearly = resample_bars(_daily(), "year")
    assert len(yearly) == 1
    assert list(yearly["open"]) == [10.0]
    assert list(yearly["high"]) == [18.0]
    assert list(yearly["low"]) == [9.0]
    assert list(yearly["close"]) == [17.0]
    assert list(yearly["volume"]) == [2800.0]


def test_quarter_supported():
    quarterly = resample_bars(_daily(), "quarter")
    assert list(quarterly["date"].dt.strftime("%Y-%m-%d")) == ["2026-02-03", "2026-05-06"]
    assert list(quarterly["volume"]) == [2100.0, 700.0]


def test_unsupported_period_raises():
    with pytest.raises(ValueError, match="unsupported period"):
        resample_bars(_daily(), "half_year")
    assert "half_year" not in BAR_PERIODS


def _business_days(count: int = 60) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=count)
    close = pd.Series(range(100, 100 + count), index=dates, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 1,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": 1000.0,
            "amount": 10000.0,
        }
    )


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import main as main_mod

    monkeypatch.setattr(main_mod, "read_quotes", lambda code, start=None, end=None: _daily())
    return TestClient(main_mod.app)


@pytest.fixture
def long_client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import main as main_mod

    monkeypatch.setattr(main_mod, "read_quotes", lambda code, start=None, end=None: _business_days())
    return TestClient(main_mod.app)


def test_api_weekly_bars_are_fewer_and_dated_last_trading_day(client):
    payload = client.get("/api/indicators/000001", params={"period": "week"}).json()
    assert payload["period"] == "week"
    assert [r["date"][:10] for r in payload["rows"]] == ["2026-01-08", "2026-02-03", "2026-05-06"]


def test_api_indicators_computed_on_resampled_close(long_client):
    daily = long_client.get("/api/indicators/000001").json()["rows"]
    weekly = long_client.get("/api/indicators/000001", params={"period": "week"}).json()["rows"]
    assert len(weekly) < len(daily)
    expected = sum(r["close"] for r in weekly[-5:]) / 5
    assert weekly[-1]["ma5"] == pytest.approx(expected, abs=1e-6)


def test_api_rejects_unknown_period(client):
    assert client.get("/api/indicators/000001", params={"period": "hourly"}).status_code == 400
