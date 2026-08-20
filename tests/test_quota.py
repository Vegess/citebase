from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.models.models import QuestionUsage
from app.services import quota


def _db(app_client):
    from app.core.database import SessionLocal

    return SessionLocal()


def test_global_cap_blocks_71st_question(app_client, monkeypatch):
    monkeypatch.setattr(quota.settings, "daily_question_cap", 70)
    monkeypatch.setattr(quota.settings, "per_user_daily_cap", 100)
    db = _db(app_client)
    try:
        for _ in range(70):
            quota.reserve_question(db, "user-1")
        db.commit()

        with pytest.raises(HTTPException) as error:
            quota.reserve_question(db, "user-2")

        assert error.value.status_code == 429
        assert "daily AI quota" in error.value.detail
        assert error.value.headers["Retry-After"]
    finally:
        db.close()


def test_per_user_cap_blocks_users_11th_question(app_client, monkeypatch):
    monkeypatch.setattr(quota.settings, "daily_question_cap", 70)
    monkeypatch.setattr(quota.settings, "per_user_daily_cap", 10)
    db = _db(app_client)
    try:
        for _ in range(10):
            quota.reserve_question(db, "user-1")
        db.commit()

        with pytest.raises(HTTPException) as error:
            quota.reserve_question(db, "user-1")

        assert error.value.status_code == 429
        assert "daily question limit" in error.value.detail
    finally:
        db.close()


def test_counters_reset_on_new_date(app_client, monkeypatch):
    monkeypatch.setattr(quota.settings, "daily_question_cap", 1)
    monkeypatch.setattr(quota.settings, "per_user_daily_cap", 1)
    db = _db(app_client)
    try:
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        quota.reserve_question(db, "user-1", now=yesterday)
        db.commit()

        quota.reserve_question(db, "user-1")
        db.commit()

        usage_dates = {row.usage_date for row in db.query(QuestionUsage).all()}
        assert len(usage_dates) == 2
    finally:
        db.close()


def test_user_under_both_caps_is_not_blocked(app_client, monkeypatch):
    monkeypatch.setattr(quota.settings, "daily_question_cap", 2)
    monkeypatch.setattr(quota.settings, "per_user_daily_cap", 2)
    db = _db(app_client)
    try:
        quota.reserve_question(db, "user-1")
        db.commit()
        quota.reserve_question(db, "user-2")
        db.commit()
    finally:
        db.close()