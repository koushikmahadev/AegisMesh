"""
Pytest configuration and fixtures for FloodWatch.
Provides mock model fallback and cache reset between tests.
"""
import os
os.environ["FW_PREWARM"] = "none"
import pytest
import torch
from unittest.mock import MagicMock
from src.api import CACHE

class MockSegformerModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.config = MagicMock()
        self.config.id2label = {0: "background", 1: "flooded", 2: "natural_water"}

    def forward(self, pixel_values):
        B, C, H, W = pixel_values.shape
        logits = torch.zeros((B, 3, H // 4, W // 4), dtype=pixel_values.dtype, device=pixel_values.device)
        logits[:, 0, :, :] = 2.0  # Background default
        if B > 1:
            logits[1, 1, 10:40, 10:40] = 10.0  # Simulated flooded zone on post-event
        return MagicMock(logits=logits)

    def eval(self):
        return self

    def half(self):
        return self

    def to(self, *args, **kwargs):
        return self


@pytest.fixture(autouse=True)
def clean_cache_before_each_test():
    """Ensure clean LRU cache before each test runs."""
    with CACHE.lock:
        CACHE.cache.clear()
    yield
    with CACHE.lock:
        CACHE.cache.clear()


@pytest.fixture(autouse=True)
def fallback_mock_model_if_needed(monkeypatch):
    """If real model weights do not exist or are corrupted, automatically mock get_model."""
    from src import flood_inference
    weights_path = os.path.join(flood_inference.MODEL_DIR, "model.safetensors")
    bin_path = os.path.join(flood_inference.MODEL_DIR, "pytorch_model.bin")
    if not (os.path.exists(weights_path) or os.path.exists(bin_path)):
        mock_instance = MockSegformerModel()
        monkeypatch.setattr(flood_inference, "get_model", lambda: mock_instance)
