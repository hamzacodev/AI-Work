from fastapi.testclient import TestClient

from app.api.demo import RECORDED
from main import app


def test_the_recorded_run_is_a_real_finished_deal_in_the_deal_shape():
    r = TestClient(app).get("/demo/recorded")
    assert r.status_code == 200
    d = r.json()
    assert d["recorded"] is True and d["model"] and d["recorded_at"] and d["status"] == "accepted"
    assert len(d["vendors"]) >= 2 and all(v["messages"] for v in d["vendors"])
    assert d["accepted_vendor_id"] in {v["id"] for v in d["vendors"]}


def test_the_recorded_run_has_no_personal_details():
    text = RECORDED.read_text().lower()
    assert "adiala" not in text and "@" not in text and "+92" not in text
