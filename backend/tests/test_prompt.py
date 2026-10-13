from app.api.main import build_system_prompt


def test_system_prompt_contains_redlines_and_context():
    prompt = build_system_prompt("## 行情摘要（300001）")
    assert "不给买卖点" in prompt
    assert "不预测目标价" in prompt
    assert "只能引用" in prompt
    assert "## 行情摘要（300001）" in prompt
