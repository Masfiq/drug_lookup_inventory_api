import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def ndcs(body: dict[str, object]) -> list[str]:
    items = body["items"]
    assert isinstance(items, list)
    return [str(item["product_ndc"]) for item in items]


def test_health_reports_loaded_data(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["products"] == 17
    assert body["last_load"] is not None


def test_search_by_brand_name(client: TestClient) -> None:
    body = client.get("/drugs/search", params={"q": "Lipitor"}).json()
    assert ndcs(body)[0] == "58151-155"
    assert body["items"][0]["score"] == 1.0
    assert body["query"] == "lipitor"


@pytest.mark.parametrize(
    ("typo", "expected_generic"),
    [("atorvastatn", "atorvastatin"), ("metfromin", "metformin"), ("ibuprofin", "ibuprofen")],
)
def test_search_tolerates_typos(client: TestClient, typo: str, expected_generic: str) -> None:
    body = client.get("/drugs/search", params={"q": typo}).json()
    assert body["total"] >= 1
    assert all(expected_generic in str(i["generic_name"]).lower() for i in body["items"])


def test_search_paginates(client: TestClient) -> None:
    first = client.get("/drugs/search", params={"q": "insulin glargine", "limit": 1}).json()
    second = client.get(
        "/drugs/search", params={"q": "insulin glargine", "limit": 1, "offset": 1}
    ).json()
    assert first["total"] == second["total"] == 2
    assert ndcs(first) != ndcs(second)


def test_search_with_no_match(client: TestClient) -> None:
    body = client.get("/drugs/search", params={"q": "zzqqxx"}).json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.parametrize("params", [{"q": "a"}, {}, {"q": "lipitor", "limit": 0}])
def test_search_validation(client: TestClient, params: dict[str, str | int]) -> None:
    response = client.get("/drugs/search", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_search_results_are_cached(client: TestClient) -> None:
    first = client.get("/drugs/search", params={"q": "lipitor"})
    second = client.get("/drugs/search", params={"q": "  LIPITOR "})  # same normalized query
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert first.json() == second.json()
    assert client.get("/health").json()["search_cache"]["hits"] == 1


def test_product_detail(client: TestClient) -> None:
    body = client.get("/drugs/58151-155").json()
    assert body["brand_name"] == "Lipitor"
    assert body["ingredients"] == [
        {"name": "ATORVASTATIN CALCIUM TRIHYDRATE", "strength": "10 mg/1"}
    ]
    assert body["routes"] == [{"name": "ORAL"}]
    assert {p["package_ndc"] for p in body["packages"]} >= {"58151-155-77"}


def test_product_detail_404(client: TestClient) -> None:
    response = client.get("/drugs/0000-0000")
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "No product with NDC 0000-0000",
        "details": {"product_ndc": "0000-0000"},
    }


def test_by_ingredient_prefix_is_case_insensitive(client: TestClient) -> None:
    body = client.get("/drugs/by-ingredient", params={"name": "METFORMIN"}).json()
    assert body["total"] == 2
    assert set(ndcs(body)) == {"71610-554", "71610-920"}
    assert body["items"][0]["ingredients"][0]["name"] == "METFORMIN HYDROCHLORIDE"


def test_by_ingredient_treats_wildcards_as_text(client: TestClient) -> None:
    body = client.get("/drugs/by-ingredient", params={"name": "%%"}).json()
    assert body["total"] == 0  # "%" is escaped, not a LIKE wildcard


def test_search_page_is_served(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "Drug Lookup" in page.text


def test_unknown_route_uses_error_shape(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
