import json
from pathlib import Path

from src.schema import RawArticle, WeekMeta

FIXTURES = Path(__file__).parent / "fixtures"


def test_import_and_fixture_load():
    raw = json.loads((FIXTURES / "raw_articles_overseas.json").read_text(encoding="utf-8"))
    week = json.loads((FIXTURES / "week_meta.json").read_text(encoding="utf-8"))
    assert len(raw) >= 8
    assert WeekMeta.from_dict(week[0]["week"]).week_key == "8월 2주"
    assert all(RawArticle.from_dict(d).published_at.tzinfo is not None for d in raw)
