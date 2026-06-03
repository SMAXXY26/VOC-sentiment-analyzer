"""Tests for the semantic request scheduler (analyzer/scheduler.py).
Uses a stub embed_fn so it's deterministic and needs no model/network."""

import math

from analyzer.scheduler import schedule, semantic_order


def _stub_embed(texts):
    # Place each text on the unit circle at an angle set by its leading int. The
    # scheduler normalises vectors and orders by cosine similarity, so points stay
    # put under normalisation and "nearest by cosine" == "nearest by leading int".
    # (A 1-D embedding would be wrong here: every positive value normalises to [1.0].)
    out = []
    for t in texts:
        theta = float(t.split()[0]) * 0.5  # keep max angular gap < pi
        out.append([math.cos(theta), math.sin(theta)])
    return out


def test_trivial_inputs_return_identity():
    assert semantic_order([]) == []
    assert semantic_order(["a"]) == [0]
    assert semantic_order(["a", "b"]) == [0, 1]


def test_orders_by_semantic_adjacency():
    texts = ["5 e", "1 a", "4 d", "2 b", "3 c"]
    order = semantic_order(texts, embed_fn=_stub_embed)
    # Starts at index 0 ("5"), then walks to the nearest unused each step: 5→4→3→2→1.
    assert order == [0, 2, 4, 3, 1]
    # Every index appears exactly once (it's a permutation).
    assert sorted(order) == list(range(len(texts)))


def test_schedule_reorders_items_by_key():
    items = [{"id": i, "text": f"{v} x"} for i, v in enumerate([5, 1, 4, 2, 3])]
    out = schedule(items, key=lambda it: it["text"], embed_fn=_stub_embed)
    assert [it["text"].split()[0] for it in out] == ["5", "4", "3", "2", "1"]
    # Same items, just reordered — none lost or duplicated.
    assert sorted(it["id"] for it in out) == [0, 1, 2, 3, 4]


def test_falls_back_to_identity_on_embed_failure():
    def boom(_):
        raise RuntimeError("embedder down")

    texts = ["a", "b", "c", "d"]
    assert semantic_order(texts, embed_fn=boom) == [0, 1, 2, 3]
