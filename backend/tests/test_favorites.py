"""favorites 表与 watchlist 替换的存储层测试。"""

import pandas as pd
import pytest

from app.data.storage import (
    add_favorites,
    get_conn,
    read_favorites,
    read_watchlist,
    remove_favorite,
    replace_watchlist,
    replace_watchlist_by_codes,
)


def _conn(tmp_path):
    return get_conn(tmp_path / "test.sqlite")


def test_add_favorites_inserts_two(tmp_path):
    conn = _conn(tmp_path)
    added, skipped = add_favorites(conn, [("000001", "平安银行"), ("600519", "贵州茅台")])
    assert (added, skipped) == (2, 0)


def test_add_favorites_skips_existing(tmp_path):
    conn = _conn(tmp_path)
    add_favorites(conn, [("000001", "平安银行")])
    added, skipped = add_favorites(conn, [("000001", "平安银行"), ("600519", "贵州茅台")])
    assert (added, skipped) == (1, 1)


def test_add_favorites_zfills_short_code(tmp_path):
    conn = _conn(tmp_path)
    add_favorites(conn, [("1", "测试")])
    frame = read_favorites(conn)
    assert frame.loc[0, "code"] == "000001"


@pytest.mark.parametrize("bad", ["abc", "1234567", "12ab45"])
def test_add_favorites_skips_invalid_code(tmp_path, bad):
    conn = _conn(tmp_path)
    added, skipped = add_favorites(conn, [(bad, "非法")])
    assert (added, skipped) == (0, 1)


def test_add_favorites_left_pads_numeric_code(tmp_path):
    conn = _conn(tmp_path)
    added, skipped = add_favorites(conn, [("12345", "补位")])
    assert (added, skipped) == (1, 0)
    assert read_favorites(conn).loc[0, "code"] == "012345"


def test_remove_favorite_returns_true_then_false(tmp_path):
    conn = _conn(tmp_path)
    add_favorites(conn, [("000001", "平安银行")])
    assert remove_favorite(conn, "000001") is True
    assert remove_favorite(conn, "000001") is False


def test_remove_favorite_zfills_code(tmp_path):
    conn = _conn(tmp_path)
    add_favorites(conn, [("000001", "平安银行")])
    assert remove_favorite(conn, "1") is True
    assert read_favorites(conn).empty


def test_read_favorites_orders_by_added_at_then_code(tmp_path):
    conn = _conn(tmp_path)
    add_favorites(conn, [("600519", "贵州茅台"), ("000001", "平安银行")], added_at="2026-10-13T10:00:00")
    add_favorites(conn, [("300750", "宁德时代")], added_at="2026-10-13T09:00:00")
    codes = read_favorites(conn)["code"].tolist()
    assert codes == ["300750", "000001", "600519"]


def test_read_favorites_empty_initially(tmp_path):
    conn = _conn(tmp_path)
    frame = read_favorites(conn)
    assert list(frame.columns) == ["code", "name", "added_at"]
    assert frame.empty


def test_replace_watchlist_by_codes_writes_rank_and_score(tmp_path):
    conn = _conn(tmp_path)
    rows = pd.DataFrame(
        [
            {"code": "600519", "name": "贵州茅台", "rank": 1, "score": 91.5},
            {"code": "000001", "name": "平安银行", "rank": 2, "score": 80.25},
        ]
    )
    assert replace_watchlist_by_codes(conn, rows) == 2
    stored = read_watchlist(conn)
    assert stored["code"].tolist() == ["600519", "000001"]
    assert stored["score"].tolist() == pytest.approx([91.5, 80.25])


def test_replace_watchlist_by_codes_defaults_score(tmp_path):
    conn = _conn(tmp_path)
    rows = pd.DataFrame([{"code": "600519", "name": "贵州茅台", "rank": 1}])
    replace_watchlist_by_codes(conn, rows)
    assert read_watchlist(conn)["score"].tolist() == pytest.approx([0.0])


def test_replace_watchlist_by_codes_replaces_previous(tmp_path):
    conn = _conn(tmp_path)
    replace_watchlist_by_codes(conn, pd.DataFrame([{"code": "600519", "name": "贵州茅台", "rank": 1}]))
    replace_watchlist_by_codes(conn, pd.DataFrame([{"code": "000001", "name": "平安银行", "rank": 1}]))
    assert read_watchlist(conn)["code"].tolist() == ["000001"]


def test_replace_watchlist_leaves_favorites_untouched(tmp_path):
    conn = _conn(tmp_path)
    add_favorites(conn, [("600519", "贵州茅台")])
    replace_watchlist(conn, pd.DataFrame([{"code": "000001", "name": "平安银行", "score": 90.0, "rank": 1}]))
    assert read_favorites(conn)["code"].tolist() == ["600519"]


def test_replace_watchlist_by_codes_leaves_favorites_untouched(tmp_path):
    conn = _conn(tmp_path)
    add_favorites(conn, [("600519", "贵州茅台")])
    replace_watchlist_by_codes(conn, pd.DataFrame([{"code": "000001", "name": "平安银行", "rank": 1}]))
    assert read_favorites(conn)["code"].tolist() == ["600519"]


def test_add_favorites_does_not_touch_watchlist(tmp_path):
    conn = _conn(tmp_path)
    replace_watchlist_by_codes(conn, pd.DataFrame([{"code": "000001", "name": "平安银行", "rank": 1}]))
    add_favorites(conn, [("600519", "贵州茅台")])
    assert read_watchlist(conn)["code"].tolist() == ["000001"]
    assert read_favorites(conn)["code"].tolist() == ["600519"]