"""Persistent evidence and review-authority regressions."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from instabotai.evidence_library import (
    EvidenceConflictError,
    EvidenceLibraryCreate,
    EvidenceLibraryStore,
    EvidenceLibraryUpdate,
    EvidenceNotFoundError,
)
from instabotai.settings import Settings
from instabotai.storage import STATE_SCHEMA_VERSION, open_state_connection, upgrade_state_database
from instabotai.web import create_app


def payload(*, content: str = "Approved product description") -> EvidenceLibraryCreate:
    return EvidenceLibraryCreate(
        title="Autumn launch facts",
        source="https://example.org/product-brief",
        content=content,
        confidence=0.65,
        origin="research",
        tags=("launch", "product"),
    )


def test_persists_searches_and_never_silently_rewrites_campaign_snapshots(
    tmp_path: Path,
) -> None:
    path = str(tmp_path / "state.sqlite3")
    library = EvidenceLibraryStore(path)
    entry = library.create(payload())
    assert entry.review_status == "unverified"
    assert entry.origin == "research"
    assert entry.library_id
    assert entry.as_campaign_evidence().evidence_id == "library-" + entry.library_id
    original_snapshot = entry.as_campaign_evidence()
    assert len(library.list(query="autumn")) == 1
    assert len(library.list(query="EXAMPLE.ORG")) == 1
    assert library.list(query="does not exist") == ()
    assert library.list(query="%") == ()

    reviewed = library.update(
        entry.library_id,
        EvidenceLibraryUpdate(
            expected_updated_at=entry.updated_at,
            review_status="reviewed",
            tags=("launch", "seasonal"),
            note="Read the original source.",
        ),
    )
    assert reviewed.review_status == "reviewed"
    assert reviewed.tags == ("launch", "seasonal")
    assert reviewed.note

    edited = library.update(
        entry.library_id,
        EvidenceLibraryUpdate(
            expected_updated_at=reviewed.updated_at,
            content="Revised source text that needs a fresh review.",
            review_status="reviewed",
        ),
    )
    assert edited.review_status == "unverified"
    assert original_snapshot.content == "Approved product description"
    assert edited.as_campaign_evidence().content != original_snapshot.content
    assert library.get(entry.library_id).content == edited.content

    reopened = EvidenceLibraryStore(path)
    assert reopened.get(entry.library_id).review_status == "unverified"
    assert reopened.get(entry.library_id).content == edited.content
    assert reopened.list(offset=1) == ()


def test_stale_edits_and_deletes_fail_closed(tmp_path: Path) -> None:
    path = str(tmp_path / "state.sqlite3")
    library = EvidenceLibraryStore(path)
    original = library.create(payload())
    changed = library.update(
        original.library_id,
        EvidenceLibraryUpdate(
            expected_updated_at=original.updated_at,
            review_status="reviewed",
        ),
    )
    with pytest.raises(EvidenceConflictError, match="reload"):
        library.update(
            original.library_id,
            EvidenceLibraryUpdate(
                expected_updated_at=original.updated_at,
                content="stale overwrite",
            ),
        )
    with pytest.raises(EvidenceConflictError, match="reload"):
        library.delete(original.library_id, expected_updated_at=original.updated_at)
    assert library.get(original.library_id).review_status == "reviewed"

    library.delete(original.library_id, expected_updated_at=changed.updated_at)
    with pytest.raises(EvidenceNotFoundError):
        library.get(original.library_id)
    with pytest.raises(EvidenceNotFoundError):
        library.delete(original.library_id, expected_updated_at=changed.updated_at)


def test_review_resets_only_when_source_content_or_confidence_changes(tmp_path: Path) -> None:
    library = EvidenceLibraryStore(str(tmp_path / "state.sqlite3"))
    entry = library.create(payload())
    reviewed = library.update(
        entry.library_id,
        EvidenceLibraryUpdate(
            expected_updated_at=entry.updated_at,
            review_status="reviewed",
        ),
    )
    renamed = library.update(
        entry.library_id,
        EvidenceLibraryUpdate(
            expected_updated_at=reviewed.updated_at, title="Verified seasonal details",
        ),
    )
    assert renamed.review_status == "reviewed"
    modified = library.update(
        entry.library_id,
        EvidenceLibraryUpdate(
            expected_updated_at=renamed.updated_at,
            confidence=0.2,
        ),
    )
    assert modified.review_status == "unverified"


def test_schema_v4_upgrades_v3_with_backup_and_keeps_state(tmp_path: Path) -> None:
    path = tmp_path / "old-state.sqlite3"
    upgrade_state_database(str(path))
    with open_state_connection(str(path)) as conn:
        conn.execute("DROP TABLE evidence_library")
        conn.execute("UPDATE instabotai_schema SET version = 3")
    report = upgrade_state_database(str(path))
    assert report.schema_version == STATE_SCHEMA_VERSION == 4
    assert report.backup_path is not None
    assert Path(report.backup_path).exists()
    assert "evidence_library" in report.managed_tables
    assert upgrade_state_database(str(path)).migrated is False


async def test_local_library_api_create_search_review_edit_and_delete(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None, state_db_path=str(tmp_path / "web.sqlite3"), ui_open_browser=False,
    )
    transport = httpx.ASGITransport(app=create_app(settings=settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post("/api/evidence-library", json=payload().model_dump())
        assert created.status_code == 201, created.text
        entry = created.json()
        assert entry["review_status"] == "unverified"
        assert len(entry["library_id"]) == 32
        assert (await client.get("/api/evidence-library?query=autumn")).json()[0] == entry
        assert (await client.get("/api/evidence-library?query=%25")).json() == []
        assert (await client.get("/api/evidence-library?limit=0")).status_code == 422

        reviewed = await client.patch(
            "/api/evidence-library/" + entry["library_id"],
            json={
                "expected_updated_at": entry["updated_at"],
                "review_status": "reviewed",
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        updated = reviewed.json()
        assert updated["review_status"] == "reviewed"
        stale = await client.patch(
            "/api/evidence-library/" + entry["library_id"],
            json={
                "expected_updated_at": entry["updated_at"],
                "note": "stale",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "evidence_conflict"

        content_edit = await client.patch(
            "/api/evidence-library/" + entry["library_id"],
            json={
                "expected_updated_at": updated["updated_at"],
                "content": "Changed content after review",
            },
        )
        assert content_edit.status_code == 200, content_edit.text
        assert content_edit.json()["review_status"] == "unverified"
        assert (await client.post("/api/evidence-library", json={
            **payload().model_dump(), "review_status": "reviewed",
        })).status_code == 422

        deleted = await client.request(
            "DELETE",
            "/api/evidence-library/" + entry["library_id"],
            json={"expected_updated_at": content_edit.json()["updated_at"]},
        )
        assert deleted.status_code == 204
        assert (await client.get("/api/evidence-library/" + entry["library_id"])).status_code == 404


def test_in_memory_library_keeps_connection_for_its_lifetime() -> None:
    library = EvidenceLibraryStore(":memory:")
    entry = library.create(payload())
    assert library.get(entry.library_id).content == payload().content
    library.close()
