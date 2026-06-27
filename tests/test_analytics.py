"""Mocked unit tests for the analytics modules: drift, clustering, active learning.

All Qdrant / LLM / embedder calls are patched, so these run in CI with no live
services (same contract as test_pipeline.py). They cover the pure math, the
alert-threshold logic, and the Qdrant interaction shape of each module.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from analyzer import active_learning, clustering, drift

# ── drift: pure helpers ─────────────────────────────────────────────────────────


class TestDriftHelpers:
    def test_cosine_distance_identical_is_zero(self):
        v = np.array([1.0, 2.0, 3.0])
        assert drift._cosine_distance(v, v) == pytest.approx(0.0, abs=1e-6)

    def test_cosine_distance_orthogonal_is_one(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert drift._cosine_distance(a, b) == pytest.approx(1.0, abs=1e-6)

    def test_cosine_distance_zero_vector_safe(self):
        # zero-norm must not divide-by-zero; module returns max distance
        assert drift._cosine_distance(np.zeros(3), np.ones(3)) == 1.0

    def test_centroid_is_mean(self):
        c = drift._centroid([[0.0, 0.0], [2.0, 4.0]])
        assert c.tolist() == [1.0, 2.0]

    def test_centroid_empty_is_none(self):
        assert drift._centroid([]) is None

    def test_sentiment_negative_rate(self):
        payloads = [
            {"sentiment": "negative"},
            {"sentiment": "positive"},
            {"sentiment": "negative"},
            {"sentiment": "neutral"},
        ]
        assert drift._sentiment_negative_rate(payloads) == pytest.approx(0.5)

    def test_sentiment_negative_rate_empty(self):
        assert drift._sentiment_negative_rate([]) == 0.0

    def test_kl_divergence_identical_is_zero(self):
        d = {"A": 0.5, "B": 0.5}
        assert drift._kl_divergence(d, d) == pytest.approx(0.0, abs=1e-6)

    def test_kl_divergence_positive_when_different(self):
        p = {"A": 0.9, "B": 0.1}
        q = {"A": 0.1, "B": 0.9}
        assert drift._kl_divergence(p, q) > 0.0

    def test_category_dist_normalises(self):
        dist = drift._category_dist([{"category": "Billing"}, {"category": "Billing"}, {"category": "Tech"}])
        assert dist["Billing"] == pytest.approx(2 / 3)
        assert sum(dist.values()) == pytest.approx(1.0)


# ── drift: compute_drift threshold logic (export_embeddings mocked) ──────────────


def _payloads(n, sentiment="neutral", category="Billing"):
    return [{"sentiment": sentiment, "category": category, "stored_at": 1.0} for _ in range(n)]


class TestComputeDrift:
    def test_no_drift_when_windows_identical(self):
        vecs = [[1.0, 0.0, 0.0]] * 10
        with (
            patch.object(drift, "export_embeddings", side_effect=[(vecs, _payloads(10)), (vecs, _payloads(10))]),
            patch.object(drift, "_store_snapshot"),
        ):
            snap = drift.compute_drift()
        assert snap["drift_detected"] is False
        assert snap["centroid_alert"] is False
        assert snap["sentiment_alert"] is False
        assert snap["category_alert"] is False

    def test_sentiment_alert_fires(self):
        # identical vectors (no centroid drift) but recent flips fully negative
        vecs = [[1.0, 0.0, 0.0]] * 10
        with (
            patch.object(
                drift,
                "export_embeddings",
                side_effect=[(vecs, _payloads(10, sentiment="negative")), (vecs, _payloads(10, sentiment="neutral"))],
            ),
            patch.object(drift, "_store_snapshot"),
        ):
            snap = drift.compute_drift()
        assert snap["sentiment_alert"] is True
        assert snap["sentiment_shift"] == pytest.approx(1.0)
        assert snap["drift_detected"] is True

    def test_centroid_alert_fires(self):
        recent = [[0.0, 1.0, 0.0]] * 10  # orthogonal to baseline
        baseline = [[1.0, 0.0, 0.0]] * 10
        with (
            patch.object(drift, "export_embeddings", side_effect=[(recent, _payloads(10)), (baseline, _payloads(10))]),
            patch.object(drift, "_store_snapshot"),
        ):
            snap = drift.compute_drift()
        assert snap["centroid_alert"] is True
        assert snap["centroid_distance"] > drift.CENTROID_THRESHOLD
        assert snap["drift_detected"] is True

    def test_category_alert_fires(self):
        vecs = [[1.0, 0.0, 0.0]] * 10
        recent = _payloads(10, category="Tech")
        baseline = _payloads(10, category="Billing")
        with (
            patch.object(drift, "export_embeddings", side_effect=[(vecs, recent), (vecs, baseline)]),
            patch.object(drift, "_store_snapshot"),
        ):
            snap = drift.compute_drift()
        assert snap["category_alert"] is True
        assert snap["drift_detected"] is True

    def test_insufficient_data_returns_no_drift(self):
        with (
            patch.object(drift, "export_embeddings", side_effect=[([], []), ([], [])]),
            patch.object(drift, "_store_snapshot"),
        ):
            snap = drift.compute_drift()
        assert snap["drift_detected"] is False


# ── clustering ──────────────────────────────────────────────────────────────────


def _three_blobs(per=10):
    rng = np.random.default_rng(0)
    centers = [[0, 0], [10, 10], [0, 10]]
    pts, summaries = [], []
    for ci, c in enumerate(centers):
        for _ in range(per):
            pts.append((np.array(c, dtype=float) + rng.normal(0, 0.2, 2)).tolist())
            summaries.append(f"cluster {ci} item")
    return pts, [{"summary": s} for s in summaries]


class TestClustering:
    def test_best_k_finds_three_blobs(self):
        X = np.array(_three_blobs()[0])
        assert clustering._best_k(X) == 3

    def test_run_clustering_insufficient_data(self):
        with patch.object(clustering, "export_embeddings", return_value=([], [])):
            result = clustering.run_clustering()
        assert "error" in result
        assert result["n_points"] == 0

    def test_run_clustering_happy_path(self):
        vecs, payloads = _three_blobs(per=10)  # 30 points ≥ MIN_POINTS
        with (
            patch.object(clustering, "export_embeddings", return_value=(vecs, payloads)),
            patch.object(clustering, "_generate_label", return_value="Test Label"),
            patch.object(clustering, "_write_cluster_labels"),
        ):
            result = clustering.run_clustering(n_clusters=3)
        assert result["n_clusters"] == 3
        assert result["n_points"] == 30
        assert len(result["clusters"]) == 3
        assert sum(c["size"] for c in result["clusters"]) == 30
        assert all(c["label"] == "Test Label" for c in result["clusters"])


# ── active learning ─────────────────────────────────────────────────────────────


def _fake_analysis():
    return SimpleNamespace(
        enrichment=SimpleNamespace(summary="customer can't pay"),
        normalized=SimpleNamespace(original="The billing page crashed and I can't pay"),
        taxonomy=SimpleNamespace(category="Billing", subcategory="Payment Issues"),
        sentiment=SimpleNamespace(sentiment="negative"),
        pipeline_confidence=0.4,
    )


class TestActiveLearning:
    def test_enqueue_upserts_to_review_collection(self):
        client = MagicMock()
        with (
            patch.object(active_learning, "get_client", return_value=client),
            patch.object(active_learning, "embed", return_value=[0.0] * 8),
        ):
            active_learning.enqueue("fb-1", _fake_analysis())
        client.upsert.assert_called_once()
        assert client.upsert.call_args.kwargs["collection_name"] == active_learning.REVIEW_COLLECTION

    def test_get_queue_returns_payloads(self):
        client = MagicMock()
        pt = SimpleNamespace(payload={"feedback_id": "fb-1", "status": "pending"})
        client.scroll.return_value = ([pt], None)
        with patch.object(active_learning, "get_client", return_value=client):
            queue = active_learning.get_queue()
        assert queue == [{"feedback_id": "fb-1", "status": "pending"}]

    def test_submit_correction_patches_analysis_and_few_shot(self):
        client = MagicMock()
        reviewed = SimpleNamespace(
            payload={"summary": "s", "current_category": "Billing", "current_sentiment": "negative"}
        )
        client.scroll.return_value = ([reviewed], None)
        with (
            patch.object(active_learning, "get_client", return_value=client),
            patch.object(active_learning, "embed", return_value=[0.0] * 8),
        ):
            result = active_learning.submit_correction("fb-1", corrected_category="Tech", corrected_sentiment="neutral")
        assert result["ok"] is True
        # review marked reviewed + analyses patched = two set_payload calls
        assert client.set_payload.call_count == 2
        patched_collections = {c.kwargs["collection_name"] for c in client.set_payload.call_args_list}
        assert active_learning.ANALYSES_COLLECTION in patched_collections
        assert active_learning.REVIEW_COLLECTION in patched_collections
        # corrected item appended to few-shot for future RAG
        client.upsert.assert_called_once()
        assert client.upsert.call_args.kwargs["collection_name"] == active_learning.FEW_SHOT_COLLECTION

    def test_submit_correction_graceful_failure(self):
        with patch.object(active_learning, "get_client", side_effect=RuntimeError("qdrant down")):
            result = active_learning.submit_correction("fb-1", corrected_category="Tech")
        assert result["ok"] is False
        assert "error" in result
