import time

import pytest

from app.db.session import check_database


def test_unreachable_database_fails_fast_with_clear_message() -> None:
    started = time.perf_counter()
    with pytest.raises(SystemExit, match="Cannot connect to the database"):
        # Nothing listens on port 1.
        check_database("postgresql+psycopg://drugs:drugs@127.0.0.1:1/drugs")
    assert time.perf_counter() - started < 10
