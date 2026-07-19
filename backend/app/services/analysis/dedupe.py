"""Near-duplicate text detection (M6): cosine similarity over embeddings.

Pure: takes a matrix of row vectors, returns connected components (size >= 2)
of pairs at/above the similarity threshold. The worker maps indices back to
items and rebuilds `near_text` duplicate groups from these components; exact
groups are never touched.
"""

from __future__ import annotations

import numpy as np


def near_duplicate_components(
    matrix: np.ndarray, *, similarity_threshold: float
) -> list[list[int]]:
    """Connected components (union-find) of row pairs with cosine similarity
    >= threshold. Deterministic order (by smallest member index)."""
    count = matrix.shape[0]
    if count < 2:
        return []
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    normalized = matrix / norms
    similarity = normalized @ normalized.T

    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    for i in range(count):
        for j in range(i + 1, count):
            if similarity[i, j] >= similarity_threshold:
                union(i, j)

    components: dict[int, list[int]] = {}
    for index in range(count):
        components.setdefault(find(index), []).append(index)
    groups = [sorted(members) for members in components.values() if len(members) >= 2]
    return sorted(groups, key=lambda members: members[0])
