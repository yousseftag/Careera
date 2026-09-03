from datetime import datetime
from typing import Any

import pytest
from bson import ObjectId


class FakeInsertResult:
    def __init__(self, inserted_id: ObjectId) -> None:
        self.inserted_id = inserted_id


class FakeUpdateResult:
    def __init__(self, matched_count: int = 1) -> None:
        self.matched_count = matched_count


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, key: str, direction: int) -> "FakeCursor":
        reverse = direction < 0
        self._docs = sorted(
            self._docs, key=lambda d: d.get(key) or datetime.min, reverse=reverse
        )
        return self

    async def __aiter__(self):
        for doc in self._docs:
            yield dict(doc)


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    async def insert_one(self, doc: dict[str, Any]) -> FakeInsertResult:
        stored = dict(doc)
        if "_id" not in stored:
            stored["_id"] = ObjectId()
        self.docs.append(stored)
        return FakeInsertResult(stored["_id"])

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if self._matches(doc, query):
                return dict(doc)
        return None

    def find(self, query: dict[str, Any]) -> FakeCursor:
        matches = [d for d in self.docs if self._matches(d, query)]
        return FakeCursor(matches)

    @staticmethod
    def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
        for k, v in query.items():
            if isinstance(v, dict) and "$ne" in v:
                if doc.get(k) == v["$ne"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any]
    ) -> FakeUpdateResult:
        for doc in self.docs:
            if self._matches(doc, query):
                if "$set" in update:
                    for k, v in update["$set"].items():
                        if "." in k:
                            parts = k.split(".")
                            curr: Any = doc
                            for part in parts[:-1]:
                                key = (
                                    int(part)
                                    if part.isdigit() and isinstance(curr, list)
                                    else part
                                )
                                curr = curr[key]
                            last_key = (
                                int(parts[-1])
                                if parts[-1].isdigit() and isinstance(curr, list)
                                else parts[-1]
                            )
                            curr[last_key] = v
                        else:
                            doc[k] = v
                return FakeUpdateResult(matched_count=1)
        return FakeUpdateResult(matched_count=0)


class FakeDB:
    def __init__(self) -> None:
        self.users = FakeCollection()
        self.analyses = FakeCollection()
        self.career_paths = FakeCollection()
        self.refresh_tokens = FakeCollection()


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()

    async def _get_database() -> FakeDB:
        return db

    monkeypatch.setattr("app.database.connection.get_database", _get_database)
    monkeypatch.setattr("app.career.service.analysis.get_database", _get_database)
    monkeypatch.setattr(
        "app.career.service.path.get_database", _get_database, raising=False
    )
    monkeypatch.setattr("app.profile.service.profile.get_database", _get_database)
    monkeypatch.setattr(
        "app.auth.service.auth.get_database", _get_database, raising=False
    )
    monkeypatch.setattr(
        "app.auth.utils.auth.get_database", _get_database, raising=False
    )
    return db
