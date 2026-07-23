"""ColPali-family encoder wrapper (page images + queries -> 128-dim multi-vectors).

Heavy imports (torch, colpali_engine) are deferred to load() so importing the
app stays cheap; the API process loads the model lazily on first query, and
scripts/embed_batch.py loads it eagerly.

Verified against colpali-engine 0.3.x: ColQwen2/ColQwen2Processor,
processor.process_images / process_queries, model(**batch) -> (B, seq, 128),
HierarchicalTokenPooler for optional pooling.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from PIL.Image import Image

Embedding = NDArray[np.float32]  # shape (n_vectors, 128)


class ColPaliEncoder:
    def __init__(self, model_name: str, *, device: str = "auto", dtype: str = "auto") -> None:
        self.model_name = model_name
        self._device_pref = device
        self._dtype_pref = dtype
        self._model: Any = None
        self._processor: Any = None
        self._torch: Any = None
        self.device: str = ""

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self.loaded:
            return
        import torch

        model_cls, processor_cls = self._resolve_classes(self.model_name)
        device = self._resolve_device(torch)
        # bfloat16 halves memory and matches how these checkpoints ship; CPU
        # bf16 is supported by torch (slower per-op, fine for small batches).
        dtype = torch.float32 if self._dtype_pref == "float32" else torch.bfloat16
        self._model = model_cls.from_pretrained(
            self.model_name, torch_dtype=dtype, device_map=device
        ).eval()
        self._processor = processor_cls.from_pretrained(self.model_name)
        self._torch = torch
        self.device = device

    def _resolve_device(self, torch: Any) -> str:
        if self._device_pref != "auto":
            return str(self._device_pref)
        if torch.cuda.is_available():
            return "cuda"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
        return "cpu"

    @staticmethod
    def _resolve_classes(model_name: str) -> tuple[Any, Any]:
        lowered = model_name.lower()
        if "colqwen2.5" in lowered or "colqwen2_5" in lowered:
            from colpali_engine.models import ColQwen2_5, ColQwen2_5_Processor

            return ColQwen2_5, ColQwen2_5_Processor
        if "colqwen" in lowered:
            from colpali_engine.models import ColQwen2, ColQwen2Processor

            return ColQwen2, ColQwen2Processor
        if "colpali" in lowered:
            from colpali_engine.models import ColPali, ColPaliProcessor

            return ColPali, ColPaliProcessor
        raise ValueError(f"unsupported ColPali-family model: {model_name!r}")

    def _forward(self, batch: Any) -> list[Embedding]:
        torch = self._torch
        batch = batch.to(self._model.device)
        with torch.inference_mode():
            embeddings = self._model(**batch)
        mask = batch.get("attention_mask") if hasattr(batch, "get") else None
        out: list[Embedding] = []
        for i in range(embeddings.shape[0]):
            emb = embeddings[i]
            if mask is not None:
                emb = emb[mask[i].bool()]  # strip batch padding: real tokens only
            arr = np.asarray(emb.to(torch.float32).cpu().numpy(), dtype=np.float32)
            out.append(arr)
        return out

    def embed_images(self, images: Sequence[Image], *, batch_size: int = 4) -> list[Embedding]:
        self.load()
        out: list[Embedding] = []
        for i in range(0, len(images), batch_size):
            chunk = list(images[i : i + batch_size])
            batch = self._processor.process_images(chunk)
            out.extend(self._forward(batch))
        return out

    def embed_queries(self, queries: Sequence[str], *, batch_size: int = 8) -> list[Embedding]:
        self.load()
        out: list[Embedding] = []
        for i in range(0, len(queries), batch_size):
            chunk = list(queries[i : i + batch_size])
            batch = self._processor.process_queries(chunk)
            out.extend(self._forward(batch))
        return out

    def pool(self, embedding: Embedding, pool_factor: int) -> Embedding:
        """Optional hierarchical token pooling (~pool_factor x smaller storage
        while keeping late interaction). No-op for pool_factor <= 1."""
        if pool_factor <= 1:
            return embedding
        self.load()
        from colpali_engine.compression.token_pooling import HierarchicalTokenPooler

        torch = self._torch
        tensor = torch.from_numpy(np.ascontiguousarray(embedding))
        pooled = HierarchicalTokenPooler().pool_embeddings(
            [tensor], pool_factor=pool_factor, padding=True, padding_side="left"
        )
        first = pooled[0]  # works for both list-of-tensors and batched tensor
        return np.asarray(first.to(torch.float32).cpu().numpy(), dtype=np.float32)
