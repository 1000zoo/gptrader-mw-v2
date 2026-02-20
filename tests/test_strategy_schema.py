from pathlib import Path


def test_strategy_schema_sql_exists_and_has_required_columns():
    content = Path("sql/011_create_strategy.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS strategy" in content
    assert "strategy_name" in content
    assert "module_path" in content
    assert "module_name" in content
    assert "use_yn" in content
