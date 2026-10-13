import pytest

from app.assistant import llm as llm_mod
from app.screener import parse as parse_mod


class _Stream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __iter__(self):
        return iter(self._chunks)


@pytest.fixture
def fake_llm(monkeypatch):
    def _install(text_or_exc):
        if isinstance(text_or_exc, Exception):
            def _fake(messages, api_key):
                raise text_or_exc
        else:
            def _fake(messages, api_key):
                return _Stream([text_or_exc])

        monkeypatch.setattr(parse_mod, "_stream_once", _fake)

    return _install


def test_parse_query_returns_filterspec(fake_llm):
    fake_llm('{"conditions": [{"field": "pe_ttm", "op": "lte", "value": 20}], "sort_by": "pe_ttm", "top": 50}')

    spec = parse_mod.parse_query("市盈率低于20", api_key="k")

    assert spec.top == 50
    assert spec.sort_by == "pe_ttm"
    assert [(c.field, c.op, c.value) for c in spec.conditions] == [("pe_ttm", "lte", 20)]


def test_parse_query_strips_code_fence(fake_llm):
    fake_llm('```json\n{"conditions": [{"field": "pn", "op": "lte", "value": 3}]}\n```')

    spec = parse_mod.parse_query("市净率低于3", api_key="k")

    assert [c.field for c in spec.conditions] == ["pn"]


def test_parse_query_without_api_key_raises():
    with pytest.raises(parse_mod.ParseError) as exc:
        parse_mod.parse_query("随便写点什么", api_key="")

    assert exc.value.reason == "llm"


def test_parse_query_llm_failure_raises_llm_reason(fake_llm):
    fake_llm(llm_mod.LLMError("boom"))

    with pytest.raises(parse_mod.ParseError) as exc:
        parse_mod.parse_query("市盈率低", api_key="k")

    assert exc.value.reason == "llm"


def test_parse_query_non_json_output_raises_json_reason(fake_llm):
    fake_llm("我看了一下，这只股票挺不错的。")

    with pytest.raises(parse_mod.ParseError) as exc:
        parse_mod.parse_query("市盈率低", api_key="k")

    assert exc.value.reason == "json"


def test_parse_query_unknown_field_raises_schema_reason(fake_llm):
    fake_llm('{"conditions": [{"field": "no_such_field", "op": "lte", "value": 3}]}')

    with pytest.raises(parse_mod.ParseError) as exc:
        parse_mod.parse_query("随便", api_key="k")

    assert exc.value.reason == "schema"


def test_parse_query_invalid_op_raises_schema_reason(fake_llm):
    fake_llm('{"conditions": [{"field": "pe_ttm", "op": "neq", "value": 3}]}')

    with pytest.raises(parse_mod.ParseError) as exc:
        parse_mod.parse_query("随便", api_key="k")

    assert exc.value.reason == "schema"


def test_prompt_contains_every_catalog_field():
    prompt = parse_mod._prompt("选市盈率低的")

    for field in ("pe_ttm", "net_profit_yoy", "industry", "list_date"):
        assert field in prompt