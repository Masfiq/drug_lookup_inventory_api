import pytest

from app.cache import TTLCache
from app.domain.ndc import is_valid_package_ndc, is_valid_product_ndc, package_belongs_to_product


@pytest.mark.parametrize("ndc", ["0002-0095", "64980-443", "50090-7387"])
def test_valid_product_ndcs(ndc: str) -> None:
    assert is_valid_product_ndc(ndc)


@pytest.mark.parametrize(
    "ndc", [None, "", "02", "123-4567", "12345-67", "ABCDE-123", "0002-0095-00"]
)
def test_invalid_product_ndcs(ndc: str | None) -> None:
    assert not is_valid_product_ndc(ndc)


@pytest.mark.parametrize("ndc", ["0002-0095-00", "64980-443-01", "50090-7387-0"])
def test_valid_package_ndcs(ndc: str) -> None:
    assert is_valid_package_ndc(ndc)


@pytest.mark.parametrize("ndc", [None, "02", "47848-026-XX", "0002-0095", "0002-0095-000"])
def test_invalid_package_ndcs(ndc: str | None) -> None:
    assert not is_valid_package_ndc(ndc)


def test_package_belongs_to_product() -> None:
    assert package_belongs_to_product("0002-0095-00", "0002-0095")
    assert not package_belongs_to_product("0002-00951-0", "0002-0095")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_cache_hit_miss_and_expiry() -> None:
    clock = FakeClock()
    cache: TTLCache[str] = TTLCache(ttl_seconds=10, max_size=5, clock=clock)
    assert cache.get("a") is None
    cache.set("a", "apple")
    assert cache.get("a") == "apple"
    clock.now = 11
    assert cache.get("a") is None  # expired
    assert (cache.hits, cache.misses) == (1, 2)
    assert len(cache) == 0


def test_cache_evicts_least_recently_used() -> None:
    cache: TTLCache[int] = TTLCache(ttl_seconds=60, max_size=2, clock=FakeClock())
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")  # "a" is now the most recently used
    cache.set("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    cache.clear()
    assert len(cache) == 0
    assert cache.hits == 0
