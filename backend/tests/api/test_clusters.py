"""Clusters/analysis API (M6): triggers, browsing, and label editing.

Runs inside the per-test savepoint session, so seeded rows never leak into
the shared dev database.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.analysis import (
    Cluster,
    ClusterRun,
    ClusterRunStatus,
    ItemCluster,
    ItemTopic,
    Topic,
)
from app.models.item import Item, ItemStatus, ItemType
from app.models.job import Job, JobKind, JobStatus

pytestmark = pytest.mark.integration


def _seed_run_with_cluster(db_session: Session) -> tuple[ClusterRun, Cluster, list[Item]]:
    items = [
        Item(
            url_raw=f"https://www.instagram.com/reel/API{index}/",
            url_canonical=f"https://www.instagram.com/reel/API{index}/",
            item_type=ItemType.reel,
            status=ItemStatus.new,
            share_text=f"seeded text {index}",
            shared_at=datetime(2026, 7, index + 1, tzinfo=UTC),
        )
        for index in range(2)
    ]
    db_session.add_all(items)
    db_session.flush()
    run = ClusterRun(
        method="agglomerative_cosine",
        params={"distance_threshold": 0.4},
        embedding_model="mock-embedding-v1",
        status=ClusterRunStatus.succeeded,
    )
    db_session.add(run)
    db_session.flush()
    cluster = Cluster(run_id=run.id, size=len(items))
    db_session.add(cluster)
    db_session.flush()
    db_session.add_all(ItemCluster(item_id=item.id, cluster_id=cluster.id) for item in items)
    topic = Topic(name="seeded topic", slug="seeded-topic")
    db_session.add(topic)
    db_session.flush()
    db_session.add(ItemTopic(item_id=items[0].id, topic_id=topic.id, confidence=0.9))
    db_session.commit()
    return run, cluster, items


# --- triggers -----------------------------------------------------------------


def test_embed_trigger_creates_job_and_enqueues(client: TestClient, db_session: Session) -> None:
    response = client.post("/api/analysis/embed", json={})
    assert response.status_code == 202
    job = db_session.get(Job, response.json()["job_id"])
    assert job is not None
    assert job.kind is JobKind.embed_batch
    assert job.status is JobStatus.queued
    assert job.rq_job_id is not None
    assert job.payload == {"item_ids": None, "force": False}


def test_cluster_trigger_validates_threshold(client: TestClient, db_session: Session) -> None:
    assert client.post("/api/analysis/cluster", json={"distance_threshold": 0}).status_code == 422
    response = client.post("/api/analysis/cluster", json={"distance_threshold": 0.5})
    assert response.status_code == 202
    job = db_session.get(Job, response.json()["job_id"])
    assert job is not None
    assert job.kind is JobKind.cluster
    assert job.payload == {"distance_threshold": 0.5}


def test_topics_trigger_conflicts_without_any_succeeded_run(
    client: TestClient, db_session: Session
) -> None:
    # Inside the savepoint: clear runs so the state is deterministic even on a
    # long-lived dev database (rolled back afterwards).
    db_session.execute(delete(ClusterRun))
    db_session.commit()
    response = client.post("/api/analysis/topics", json={})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_cluster_run"


def test_topics_trigger_accepts_latest_succeeded_run(
    client: TestClient, db_session: Session
) -> None:
    _seed_run_with_cluster(db_session)
    response = client.post("/api/analysis/topics", json={})
    assert response.status_code == 202
    job = db_session.get(Job, response.json()["job_id"])
    assert job is not None
    assert job.kind is JobKind.topics


def test_topics_trigger_404_for_unknown_run(client: TestClient) -> None:
    response = client.post("/api/analysis/topics", json={"cluster_run_id": 999_999_999})
    assert response.status_code == 404


# --- browsing -----------------------------------------------------------------


def test_list_cluster_runs_includes_counts(client: TestClient, db_session: Session) -> None:
    run, _, _ = _seed_run_with_cluster(db_session)
    response = client.get("/api/cluster-runs")
    assert response.status_code == 200
    entry = next(item for item in response.json() if item["id"] == run.id)
    assert entry["status"] == "succeeded"
    assert entry["cluster_count"] == 1
    assert entry["embedding_model"] == "mock-embedding-v1"


def test_cluster_run_detail_includes_clusters_and_topics(
    client: TestClient, db_session: Session
) -> None:
    run, cluster, _ = _seed_run_with_cluster(db_session)
    response = client.get(f"/api/cluster-runs/{run.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["cluster_count"] == 1
    [cluster_entry] = body["clusters"]
    assert cluster_entry["id"] == cluster.id
    assert cluster_entry["size"] == 2
    assert cluster_entry["topics"] == ["seeded topic"]


def test_cluster_run_detail_404(client: TestClient) -> None:
    assert client.get("/api/cluster-runs/999999999").status_code == 404


def test_cluster_items_lists_members_without_embeddings(
    client: TestClient, db_session: Session
) -> None:
    _, cluster, items = _seed_run_with_cluster(db_session)
    response = client.get(f"/api/clusters/{cluster.id}/items")
    assert response.status_code == 200
    body = response.json()
    assert [entry["id"] for entry in body["items"]] == [item.id for item in items]
    # Embeddings are derived from private text and never serialized.
    assert "embedding" not in body["items"][0]
    assert client.get("/api/clusters/999999999/items").status_code == 404


# --- editing ------------------------------------------------------------------


def test_patch_cluster_updates_label_and_description(
    client: TestClient, db_session: Session
) -> None:
    _, cluster, _ = _seed_run_with_cluster(db_session)
    response = client.patch(
        f"/api/clusters/{cluster.id}",
        json={"label": "Edited Label", "description_md": "Edited description."},
    )
    assert response.status_code == 200
    db_session.refresh(cluster)
    assert cluster.label == "Edited Label"
    assert cluster.description_md == "Edited description."


def test_patch_cluster_is_partial(client: TestClient, db_session: Session) -> None:
    _, cluster, _ = _seed_run_with_cluster(db_session)
    cluster.label = "Original"
    cluster.description_md = "Original description."
    db_session.commit()
    response = client.patch(f"/api/clusters/{cluster.id}", json={"label": "Only Label"})
    assert response.status_code == 200
    db_session.refresh(cluster)
    assert cluster.label == "Only Label"
    assert cluster.description_md == "Original description."


def test_patch_cluster_404(client: TestClient) -> None:
    assert client.patch("/api/clusters/999999999", json={"label": "x"}).status_code == 404
