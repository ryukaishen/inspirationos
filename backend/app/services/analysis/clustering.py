"""Pure clustering wrapper (M6): agglomerative, cosine distance threshold.

Deterministic and parameter-explainable (ARCHITECTURE.md); no DB access —
takes a matrix of row vectors, returns groups of row indices. Singleton
clusters are dropped (min_cluster_size, recorded in cluster_runs.params) —
an unclustered item simply stays outside every cluster.
"""

from __future__ import annotations

import numpy as np

CLUSTER_METHOD = "agglomerative_cosine"
LINKAGE = "average"
MIN_CLUSTER_SIZE = 2


def cluster_embeddings(
    matrix: np.ndarray,
    *,
    distance_threshold: float,
    min_cluster_size: int = MIN_CLUSTER_SIZE,
) -> list[list[int]]:
    """Groups of row indices whose cosine distance clusters below the
    threshold; groups smaller than min_cluster_size are dropped. Output order
    is deterministic (by smallest member index); member order is ascending."""
    if matrix.shape[0] < 2:
        return []
    from sklearn.cluster import AgglomerativeClustering

    labels = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage=LINKAGE,
        distance_threshold=distance_threshold,
    ).fit_predict(matrix)

    by_label: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        by_label.setdefault(int(label), []).append(index)
    groups = [sorted(members) for members in by_label.values() if len(members) >= min_cluster_size]
    return sorted(groups, key=lambda members: members[0])
