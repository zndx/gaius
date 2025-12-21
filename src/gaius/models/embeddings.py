"""Nomic unified embeddings for text and vision.

The Nomic embedding models (nomic-embed-text-v1 and nomic-embed-vision-v1)
share the same 768-dimensional embedding space, enabling:
- Text-to-text similarity search
- Image-to-image similarity search
- Text-to-image and image-to-text cross-modal search

Models are loaded from HuggingFace Hub and cached in ~/.cache/huggingface/

Usage:
    from gaius.models import get_embeddings

    embeddings = get_embeddings()

    # Text embedding
    text_vec = await embeddings.embed_text("pension asset allocation")

    # Vision embedding (same space!)
    img_vec = await embeddings.embed_image("/path/to/chart.png")

    # Cross-modal similarity works!
    similarity = cosine_similarity(text_vec, img_vec)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Union
import asyncio

import numpy as np


@dataclass
class EmbeddingResult:
    """Result from an embedding operation."""

    vector: np.ndarray
    model: str
    input_type: str  # "text" or "vision"
    tokens: int = 0
    latency_ms: int = 0

    @property
    def dim(self) -> int:
        """Embedding dimension."""
        return len(self.vector)

    def to_list(self) -> list[float]:
        """Convert to Python list for JSON serialization."""
        return self.vector.tolist()


@dataclass
class BatchEmbeddingResult:
    """Result from batch embedding."""

    vectors: np.ndarray  # Shape: (n, dim)
    model: str
    input_type: str
    count: int = 0
    total_tokens: int = 0
    latency_ms: int = 0

    @property
    def dim(self) -> int:
        """Embedding dimension."""
        return self.vectors.shape[1] if len(self.vectors.shape) > 1 else 0


class NomicEmbeddings:
    """Unified text and vision embeddings using Nomic models.

    Both models produce 768-dimensional vectors in the same space,
    enabling cross-modal retrieval.
    """

    TEXT_MODEL = "nomic-ai/nomic-embed-text-v1"
    VISION_MODEL = "nomic-ai/nomic-embed-vision-v1"
    EMBEDDING_DIM = 768

    def __init__(
        self,
        device: str | None = None,
        trust_remote_code: bool = True,
    ):
        """Initialize Nomic embeddings.

        Args:
            device: Device to use ("cuda", "cpu", or None for auto)
            trust_remote_code: Trust remote code from HuggingFace
        """
        self._device = device
        self._trust_remote_code = trust_remote_code

        # Lazy-loaded models
        self._text_model = None
        self._text_tokenizer = None
        self._vision_model = None
        self._vision_processor = None

    def _get_device(self) -> str:
        """Get device to use.

        Automatically selects GPU with most free memory to avoid OOM
        when other models are loaded.
        """
        if self._device:
            return self._device

        try:
            import torch
            if not torch.cuda.is_available():
                return "cpu"

            # Find GPU with most free memory
            best_gpu = self._find_free_gpu()
            return f"cuda:{best_gpu}"
        except ImportError:
            return "cpu"

    def _find_free_gpu(self) -> int:
        """Find GPU with most free memory.

        Queries nvidia-smi to avoid loading torch prematurely.
        Falls back to GPU 0 if query fails.
        """
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                best_gpu = 0
                best_free = 0
                for line in result.stdout.strip().split("\n"):
                    parts = line.split(",")
                    if len(parts) == 2:
                        gpu_idx = int(parts[0].strip())
                        free_mb = int(parts[1].strip())
                        if free_mb > best_free:
                            best_free = free_mb
                            best_gpu = gpu_idx
                return best_gpu
        except Exception:
            pass
        return 0

    def _load_text_model(self):
        """Load text embedding model."""
        if self._text_model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer

            self._text_model = SentenceTransformer(
                self.TEXT_MODEL,
                device=self._get_device(),
                trust_remote_code=self._trust_remote_code,
            )
        except ImportError:
            # Fallback to transformers
            from transformers import AutoModel, AutoTokenizer
            import torch

            self._text_tokenizer = AutoTokenizer.from_pretrained(
                self.TEXT_MODEL,
                trust_remote_code=self._trust_remote_code,
            )
            self._text_model = AutoModel.from_pretrained(
                self.TEXT_MODEL,
                trust_remote_code=self._trust_remote_code,
            ).to(self._get_device())

    def _load_vision_model(self):
        """Load vision embedding model."""
        if self._vision_model is not None:
            return

        from transformers import AutoModel, AutoProcessor

        self._vision_processor = AutoProcessor.from_pretrained(
            self.VISION_MODEL,
            trust_remote_code=self._trust_remote_code,
        )
        self._vision_model = AutoModel.from_pretrained(
            self.VISION_MODEL,
            trust_remote_code=self._trust_remote_code,
        ).to(self._get_device())

    async def embed_text(
        self,
        text: str,
        normalize: bool = True,
    ) -> EmbeddingResult:
        """Embed a single text string.

        Args:
            text: Text to embed
            normalize: If True, L2-normalize the vector

        Returns:
            EmbeddingResult with 768-dim vector
        """
        import time
        start = time.perf_counter()

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        vector = await loop.run_in_executor(
            None, self._embed_text_sync, text, normalize
        )

        latency_ms = int((time.perf_counter() - start) * 1000)

        return EmbeddingResult(
            vector=vector,
            model=self.TEXT_MODEL,
            input_type="text",
            tokens=len(text.split()),  # Approximate
            latency_ms=latency_ms,
        )

    def _embed_text_sync(self, text: str, normalize: bool) -> np.ndarray:
        """Synchronous text embedding."""
        self._load_text_model()

        # Check if using sentence-transformers
        if hasattr(self._text_model, 'encode'):
            vector = self._text_model.encode(
                text,
                normalize_embeddings=normalize,
                convert_to_numpy=True,
            )
            return vector

        # Fallback to raw transformers
        import torch

        inputs = self._text_tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=8192,
        ).to(self._get_device())

        with torch.no_grad():
            outputs = self._text_model(**inputs)
            # Mean pooling
            vector = outputs.last_hidden_state.mean(dim=1).squeeze()

            if normalize:
                vector = vector / vector.norm()

            return vector.cpu().numpy()

    async def embed_texts(
        self,
        texts: list[str],
        normalize: bool = True,
        batch_size: int = 32,
    ) -> BatchEmbeddingResult:
        """Embed multiple texts.

        Args:
            texts: List of texts to embed
            normalize: If True, L2-normalize vectors
            batch_size: Batch size for processing

        Returns:
            BatchEmbeddingResult with (n, 768) array
        """
        import time
        start = time.perf_counter()

        loop = asyncio.get_event_loop()
        vectors = await loop.run_in_executor(
            None, self._embed_texts_sync, texts, normalize, batch_size
        )

        latency_ms = int((time.perf_counter() - start) * 1000)

        return BatchEmbeddingResult(
            vectors=vectors,
            model=self.TEXT_MODEL,
            input_type="text",
            count=len(texts),
            total_tokens=sum(len(t.split()) for t in texts),
            latency_ms=latency_ms,
        )

    def _embed_texts_sync(
        self,
        texts: list[str],
        normalize: bool,
        batch_size: int,
    ) -> np.ndarray:
        """Synchronous batch text embedding."""
        self._load_text_model()

        if hasattr(self._text_model, 'encode'):
            vectors = self._text_model.encode(
                texts,
                normalize_embeddings=normalize,
                convert_to_numpy=True,
                batch_size=batch_size,
                show_progress_bar=False,
            )
            return vectors

        # Fallback: process in batches
        import torch

        all_vectors = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            inputs = self._text_tokenizer(
                batch,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=8192,
            ).to(self._get_device())

            with torch.no_grad():
                outputs = self._text_model(**inputs)
                vectors = outputs.last_hidden_state.mean(dim=1)
                if normalize:
                    vectors = vectors / vectors.norm(dim=1, keepdim=True)
                all_vectors.append(vectors.cpu().numpy())

        return np.vstack(all_vectors)

    async def embed_image(
        self,
        image: Union[str, Path, "Image.Image"],
        normalize: bool = True,
    ) -> EmbeddingResult:
        """Embed an image.

        Args:
            image: Path to image file or PIL Image object
            normalize: If True, L2-normalize the vector

        Returns:
            EmbeddingResult with 768-dim vector (same space as text!)
        """
        import time
        start = time.perf_counter()

        loop = asyncio.get_event_loop()
        vector = await loop.run_in_executor(
            None, self._embed_image_sync, image, normalize
        )

        latency_ms = int((time.perf_counter() - start) * 1000)

        return EmbeddingResult(
            vector=vector,
            model=self.VISION_MODEL,
            input_type="vision",
            latency_ms=latency_ms,
        )

    def _embed_image_sync(
        self,
        image: Union[str, Path, "Image.Image"],
        normalize: bool,
    ) -> np.ndarray:
        """Synchronous image embedding."""
        from PIL import Image
        import torch

        self._load_vision_model()

        # Load image if path
        if isinstance(image, (str, Path)):
            image = Image.open(image).convert("RGB")

        # Process image
        inputs = self._vision_processor(
            images=image,
            return_tensors="pt",
        ).to(self._get_device())

        with torch.no_grad():
            outputs = self._vision_model(**inputs)
            # Use pooled output or mean of last hidden state
            if hasattr(outputs, 'pooler_output') and outputs.pooler_output is not None:
                vector = outputs.pooler_output.squeeze()
            else:
                vector = outputs.last_hidden_state.mean(dim=1).squeeze()

            if normalize:
                vector = vector / vector.norm()

            return vector.cpu().numpy()

    async def embed_images(
        self,
        images: list[Union[str, Path, "Image.Image"]],
        normalize: bool = True,
        batch_size: int = 8,
    ) -> BatchEmbeddingResult:
        """Embed multiple images.

        Args:
            images: List of image paths or PIL Images
            normalize: If True, L2-normalize vectors
            batch_size: Batch size for processing

        Returns:
            BatchEmbeddingResult with (n, 768) array
        """
        import time
        start = time.perf_counter()

        loop = asyncio.get_event_loop()
        vectors = await loop.run_in_executor(
            None, self._embed_images_sync, images, normalize, batch_size
        )

        latency_ms = int((time.perf_counter() - start) * 1000)

        return BatchEmbeddingResult(
            vectors=vectors,
            model=self.VISION_MODEL,
            input_type="vision",
            count=len(images),
            latency_ms=latency_ms,
        )

    def _embed_images_sync(
        self,
        images: list,
        normalize: bool,
        batch_size: int,
    ) -> np.ndarray:
        """Synchronous batch image embedding."""
        from PIL import Image
        import torch

        self._load_vision_model()

        # Load all images
        pil_images = []
        for img in images:
            if isinstance(img, (str, Path)):
                pil_images.append(Image.open(img).convert("RGB"))
            else:
                pil_images.append(img)

        # Process in batches
        all_vectors = []
        for i in range(0, len(pil_images), batch_size):
            batch = pil_images[i:i + batch_size]
            inputs = self._vision_processor(
                images=batch,
                return_tensors="pt",
            ).to(self._get_device())

            with torch.no_grad():
                outputs = self._vision_model(**inputs)
                if hasattr(outputs, 'pooler_output') and outputs.pooler_output is not None:
                    vectors = outputs.pooler_output
                else:
                    vectors = outputs.last_hidden_state.mean(dim=1)

                if normalize:
                    vectors = vectors / vectors.norm(dim=1, keepdim=True)

                all_vectors.append(vectors.cpu().numpy())

        return np.vstack(all_vectors)


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level API
# ═══════════════════════════════════════════════════════════════════════════════

_embeddings: NomicEmbeddings | None = None


def get_embeddings(device: str | None = None) -> NomicEmbeddings:
    """Get or create the Nomic embeddings singleton."""
    global _embeddings
    if _embeddings is None:
        _embeddings = NomicEmbeddings(device=device)
    return _embeddings


async def embed_text(text: str) -> np.ndarray:
    """Convenience function to embed text."""
    embeddings = get_embeddings()
    result = await embeddings.embed_text(text)
    return result.vector


async def embed_image(image: Union[str, Path]) -> np.ndarray:
    """Convenience function to embed image."""
    embeddings = get_embeddings()
    result = await embeddings.embed_image(image)
    return result.vector
