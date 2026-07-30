import os

import pytest
from sqlalchemy import create_engine, text


DATABASE_URL = os.getenv("VIDCAR_TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="VIDCAR_TEST_DATABASE_URL is not configured")
def test_postgres_is_reachable():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as connection:
        assert connection.scalar(text("select 1")) == 1
