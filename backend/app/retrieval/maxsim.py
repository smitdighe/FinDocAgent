"""VectorChord MaxSim query construction.

Verified against VectorChord 1.1.1 docs (MaxSim shipped in 0.3.0):
- column type:   vector(128)[]
- index:         CREATE INDEX ... USING vchordrq (embeddings vector_maxsim_ops)
- operator:      embeddings @# ARRAY['[..]'::vector, ...]   (negative MaxSim,
                 so ascending order == most similar first; similarity = -distance)
- tuning GUCs:   vchordrq.maxsim_refine, vchordrq.maxsim_threshold

Vector literals are built from validated floats only (never user strings), so
inlining them into SQL is injection-safe; scalar params stay bound.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from app.db.models import EMBEDDING_DIM

MAXSIM_OP = "@#"

# A ColQwen2 page is ~750-1300 patch vectors; queries are ~20-40. Anything
# beyond this is a bug upstream.
MAX_VECTORS = 8192


def format_vector(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(v):.6f}" for v in vec) + "]"


def multivector_literal(
    vectors: NDArray[np.float32] | Sequence[Sequence[float]], *, dim: int = EMBEDDING_DIM
) -> str:
    """Render a multi-vector as a `vector(dim)[]` SQL literal, validating
    shape and finiteness (floats are formatted by us — no injection surface)."""
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError(f"expected 2-D multi-vector, got shape {arr.shape}")
    n, d = arr.shape
    if d != dim:
        raise ValueError(f"expected {dim}-dim vectors, got {d}")
    if n < 1:
        raise ValueError("multi-vector must contain at least one vector")
    if n > MAX_VECTORS:
        raise ValueError(f"multi-vector too large: {n} > {MAX_VECTORS}")
    if not math.isfinite(float(arr.sum())) or not np.isfinite(arr).all():
        raise ValueError("multi-vector contains non-finite values")
    inner = ",".join(f"'{format_vector(row)}'::vector({dim})" for row in arr)
    return f"ARRAY[{inner}]::vector({dim})[]"


def maxsim_distance_expr(column: str, literal: str) -> str:
    """`column @# literal` — VectorChord's negative-MaxSim distance."""
    return f"{column} {MAXSIM_OP} {literal}"
