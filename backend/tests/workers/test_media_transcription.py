"""Reel media extraction against real Postgres: pending-reel selection,
result persistence + audit, full-text search over transcripts, and the vision
reader's budget gate / ai_requests audit. Adapters are fakes — no network, no
yt-dlp/Whisper, no Anthropic API. All text is synthetic."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.ai_request import AiRequest, AiRequestStatus
from app.models.app_settings import AppSettings
from app.models.enrichment_attempt import EnrichmentAttempt, EnrichmentSource, EnrichmentStatus
from app.models.item import Item, ItemStatus, ItemType
from app.services.ai.budget import BudgetExceededError
from app.services.enrichment.policy import CircuitBreaker
from app.services.media.pipeline import (
    DownloadedReel,
    ExtractionSettings,
    MediaUnavailableError,
    run_transcription,
    select_pending_reels,
)
from app.services.media.vision import TASK, AnthropicFrameReader

pytestmark = pytest.mark.integration


def _add_item(session: Session, code: str, **overrides: Any) -> Item:
    url = f"https://www.instagram.com/reel/{code}/"
    fields: dict[str, Any] = {
        "url_raw": url,
        "url_canonical": url,
        "shortcode": code,
        "item_type": ItemType.reel,
        "status": ItemStatus.needs_context,
    }
    fields.update(overrides)
    item = Item(**fields)
    session.add(item)
    session.flush()
    return item


class FakeDownloader:
    def __init__(self, unavailable: set[str] | None = None) -> None:
        self.unavailable = unavailable or set()
        self.urls: list[str] = []

    def download(self, url: str, workdir: Path) -> DownloadedReel:
        self.urls.append(url)
        if any(code in url for code in self.unavailable):
            raise MediaUnavailableError()
        video = workdir / "reel.mp4"
        video.write_bytes(b"fake")
        return DownloadedReel(video_path=video, caption="synthetic caption", author="creator")


class FakeTranscriber:
    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, media_path: Path) -> str:
        return self.text


def _run(
    session: Session, groups: list[Any], tmp_path: Path, downloader: FakeDownloader, text: str
):
    return run_transcription(
        session,
        groups,
        downloader=downloader,
        transcriber=FakeTranscriber(text),
        frame_reader=None,
        sample_frames=lambda path, count: [],
        workdir=tmp_path,
        settings=ExtractionSettings(),
        delay_seconds=0.0,
        jitter_seconds=0.0,
        breaker=CircuitBreaker(3),
        report=lambda line: None,
        sleep=lambda seconds: None,
    )


def test_pending_groups_repeat_shares_and_skip_non_media(db_session: Session) -> None:
    code = f"MED{uuid4().hex[:8]}"
    first = _add_item(db_session, code)
    again = _add_item(db_session, code, url_raw=f"https://instagram.com/reel/{code}/?igsh=x")
    story = _add_item(db_session, f"{code}S", item_type=ItemType.story)

    groups = select_pending_reels(db_session, item_ids=[first.id, again.id, story.id])

    assert len(groups) == 1
    assert {item.id for item in groups[0].items} == {first.id, again.id}


def test_run_persists_text_audits_and_skips_done_reels(db_session: Session, tmp_path: Path) -> None:
    code = f"MED{uuid4().hex[:8]}"
    first = _add_item(db_session, code)
    again = _add_item(db_session, code)
    gone = _add_item(db_session, f"{code}GONE")
    ids = [first.id, again.id, gone.id]
    downloader = FakeDownloader(unavailable={f"{code}GONE"})

    summary = _run(
        db_session,
        select_pending_reels(db_session, item_ids=ids),
        tmp_path,
        downloader,
        "synthetic spoken walkthrough of a budgeting spreadsheet",
    )

    assert summary.counts == {EnrichmentStatus.success: 1, EnrichmentStatus.not_found: 1}
    assert len(downloader.urls) == 2, "a repeat-shared reel is downloaded once"
    for item in (first, again):
        db_session.refresh(item)
        assert item.transcript == "synthetic spoken walkthrough of a budgeting spreadsheet"
        assert item.enriched_source is EnrichmentSource.ytdlp
        assert item.status is ItemStatus.new
    db_session.refresh(gone)
    assert gone.transcript is None
    assert gone.status is ItemStatus.needs_context

    attempts = db_session.scalars(
        select(EnrichmentAttempt).where(EnrichmentAttempt.item_id.in_(ids))
    ).all()
    assert len(attempts) == 3
    assert {a.source for a in attempts} == {EnrichmentSource.ytdlp}

    assert select_pending_reels(db_session, item_ids=ids) == [], "done reels are not redone"


def test_errored_reels_are_retried(db_session: Session) -> None:
    item = _add_item(db_session, f"MED{uuid4().hex[:8]}")
    db_session.add(
        EnrichmentAttempt(
            item_id=item.id, source=EnrichmentSource.ytdlp, status=EnrichmentStatus.blocked
        )
    )
    db_session.flush()
    assert len(select_pending_reels(db_session, item_ids=[item.id])) == 1


def test_inbox_search_finds_item_by_transcript(
    db_session: Session, client: TestClient, tmp_path: Path
) -> None:
    item = _add_item(db_session, f"MED{uuid4().hex[:8]}")
    _run(
        db_session,
        select_pending_reels(db_session, item_ids=[item.id]),
        tmp_path,
        FakeDownloader(),
        "the creator explains a quokkaflux pricing ladder",
    )

    response = client.get("/api/items", params={"search": "quokkaflux", "page_size": 50})

    assert response.status_code == 200
    found = [entry["item"] for entry in response.json()["entries"]]
    assert [entry["id"] for entry in found] == [item.id]
    assert found[0]["transcript"] == "the creator explains a quokkaflux pricing ladder"


class FakeAnthropic:
    def __init__(self, text: str) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)
        self.text = text

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1200, output_tokens=40),
            content=[SimpleNamespace(type="text", text=self.text)],
        )


def test_vision_reader_audits_call_and_maps_none(db_session: Session) -> None:
    client = FakeAnthropic("NONE")
    reader = AnthropicFrameReader(db_session, get_config(), client)

    assert reader.read_frames([b"jpeg-1", b"jpeg-2"]) == ""

    images = [b for b in client.calls[0]["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == 2
    row = db_session.scalars(
        select(AiRequest).where(AiRequest.task == TASK).order_by(AiRequest.id.desc())
    ).first()
    assert row is not None
    assert row.status is AiRequestStatus.success
    assert (row.prompt_tokens, row.completion_tokens) == (1200, 40)
    assert float(row.est_cost_usd) > 0


def test_vision_reader_refuses_over_budget_without_calling(db_session: Session) -> None:
    settings = db_session.get(AppSettings, 1)
    assert settings is not None
    settings.monthly_budget_usd = 0
    db_session.flush()
    client = FakeAnthropic("STEP 1")

    with pytest.raises(BudgetExceededError):
        AnthropicFrameReader(db_session, get_config(), client).read_frames([b"jpeg"])
    assert client.calls == []
