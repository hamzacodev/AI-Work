import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deals import split_vendors
from app.core.db import get_repo
from app.schemas.deal import VendorIn
from main import app


class FakeRepo:
    """Keeps deals in a dict. Stands in for Supabase in tests."""

    def __init__(self) -> None:
        self.deals: dict[str, dict[str, Any]] = {}

    def create_deal(self, deal: dict[str, Any], vendors: list[dict[str, Any]]) -> str:
        deal_id = str(uuid.uuid4())
        self.deals[deal_id] = {
            "id": deal_id,
            "status": "created",
            "research": None,
            **{k: deal[k] for k in ("item", "max_price", "currency")},
            "_private": {"address": deal["address"], "phone": deal["phone"]},
            "vendors": [
                {
                    "id": str(uuid.uuid4()),
                    "status": "sent",
                    "offer_price": None,
                    "recommendation": None,
                    "messages": [],
                    "events": [],
                    **v,
                }
                for v in vendors
            ],
        }
        return deal_id

    def get_deal(self, deal_id: str) -> dict[str, Any] | None:
        return self.deals.get(deal_id)


@pytest.fixture
def repo():
    r = FakeRepo()
    app.dependency_overrides[get_repo] = lambda: r
    yield r
    app.dependency_overrides.clear()


@pytest.fixture
def client(repo):
    return TestClient(app)


def payload(**over):
    base = {
        "item": "Dell XPS 15",
        "max_price": 800,
        "currency": "USD",
        "must_haves": ["16GB RAM"],
        "address": "12 Example Street, Karachi",
        "phone": "+92 300 1234567",
        "vendors": [
            {"name": "TechHub", "contact": "sales@techhub.example.com", "channel": "email"},
            {"name": "Digital Bazaar", "contact": "+92 300 1111111", "channel": "chat"},
        ],
    }
    base.update(over)
    return base


def vendors(n: int) -> list[dict]:
    return [{"name": f"V{i}", "contact": f"v{i}@x.example.com"} for i in range(n)]


# ---------- create ----------


def test_create_deal_returns_id_and_counts(client):
    res = client.post("/deals", json=payload())
    assert res.status_code == 201
    body = res.json()
    assert uuid.UUID(body["id"])
    assert body["accepted_vendors"] == 2
    assert body["skipped_vendors"] == 0


def test_vendor_cap_keeps_first_ten_and_reports_skipped(client, repo):
    res = client.post("/deals", json=payload(vendors=vendors(15)))
    assert res.status_code == 201
    assert res.json()["accepted_vendors"] == 10
    assert res.json()["skipped_vendors"] == 5
    stored = repo.deals[res.json()["id"]]["vendors"]
    assert [v["name"] for v in stored] == [f"V{i}" for i in range(10)]


def test_duplicate_contacts_are_removed_not_counted_as_skipped(client):
    dupes = [
        {"name": "A", "contact": "same@x.example.com"},
        {"name": "B", "contact": "SAME@x.example.com"},
        {"name": "C", "contact": "other@x.example.com"},
    ]
    res = client.post("/deals", json=payload(vendors=dupes))
    assert res.json()["accepted_vendors"] == 2
    assert res.json()["skipped_vendors"] == 0


@pytest.mark.parametrize(
    "over",
    [
        {"max_price": 0},
        {"max_price": -5},
        {"currency": "JPY"},
        {"item": "   "},
        {"item": "x" * 2001},
        {"address": ""},
        {"phone": "abc"},
        {"vendors": []},
        {"vendors": vendors(201)},
        {"vendors": [{"name": "A", "contact": "not-a-contact"}]},
        {"vendors": [{"name": "", "contact": "a@x.example.com"}]},
        {"vendors": [{"name": "A", "contact": "a@x.example.com", "channel": "sms"}]},
    ],
)
def test_bad_requests_are_rejected_with_422(client, over):
    assert client.post("/deals", json=payload(**over)).status_code == 422


def test_phone_is_optional(client):
    assert client.post("/deals", json=payload(phone=None)).status_code == 201
    body = payload()
    del body["phone"]
    assert client.post("/deals", json=body).status_code == 201


# ---------- get ----------


def test_get_deal_returns_contract_shape(client):
    deal_id = client.post("/deals", json=payload()).json()["id"]
    res = client.get(f"/deals/{deal_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["item"] == "Dell XPS 15"
    assert body["max_price"] == 800
    assert body["currency"] == "USD"
    assert len(body["vendors"]) == 2
    v = body["vendors"][0]
    assert set(v) >= {"id", "name", "channel", "status", "offer_price", "messages", "events"}
    assert v["status"] == "sent"


def test_get_deal_never_exposes_address_or_phone(client):
    deal_id = client.post("/deals", json=payload()).json()["id"]
    text = client.get(f"/deals/{deal_id}").text
    assert "Example Street" not in text
    assert "1234567" not in text


def test_message_uses_from_key_in_json(client, repo):
    deal_id = client.post("/deals", json=payload()).json()["id"]
    repo.deals[deal_id]["vendors"][0]["messages"] = [
        {"from": "vendor", "text": "Hi", "at": "2026-10-02T10:00:00+00:00"}
    ]
    msg = client.get(f"/deals/{deal_id}").json()["vendors"][0]["messages"][0]
    assert msg["from"] == "vendor"
    assert "from_" not in msg


def test_unknown_deal_is_404(client):
    assert client.get(f"/deals/{uuid.uuid4()}").status_code == 404


def test_malformed_id_is_422(client):
    assert client.get("/deals/not-a-uuid").status_code == 422


# ---------- helper ----------


def test_split_vendors_directly():
    vs = [VendorIn(name=f"V{i}", contact=f"v{i}@x.example.com") for i in range(4)]
    accepted, skipped = split_vendors(vs, 3)
    assert len(accepted) == 3 and skipped == 1
