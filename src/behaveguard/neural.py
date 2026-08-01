from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence


NEURAL_FORMAT_VERSION = 3


def _masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    weights = mask.unsqueeze(-1).to(values.dtype)
    return (values * weights).sum(dim=1) / weights.sum(dim=1).clamp_min(1)


class TemporalBlock(nn.Module):
    def __init__(self, input_dim: int, hidden: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(input_dim, hidden, 5, padding=2), nn.BatchNorm1d(hidden), nn.GELU(),
            nn.Conv1d(hidden, hidden, 3, padding=1), nn.BatchNorm1d(hidden), nn.GELU(),
        )

    def forward(self, values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        encoded = self.net(values.transpose(1, 2)).transpose(1, 2)
        return _masked_mean(encoded, mask)


class BehavioralSequenceNet(nn.Module):
    """BiLSTM keyboard tower + TCN mouse tower + engineered-feature fusion."""

    def __init__(self, feature_dim: int, class_count: int, embedding_dim: int = 128):
        super().__init__()
        self.keyboard = nn.LSTM(6, 48, num_layers=2, batch_first=True, bidirectional=True, dropout=0.15)
        self.mouse = TemporalBlock(6, 96)
        self.features = nn.Sequential(nn.Linear(feature_dim, 128), nn.LayerNorm(128), nn.GELU(), nn.Dropout(0.15))
        self.fusion = nn.Sequential(nn.Linear(320, 192), nn.GELU(), nn.Linear(192, embedding_dim))
        self.classifier = nn.Linear(embedding_dim, class_count)

    def forward(self, keyboard: torch.Tensor, mouse: torch.Tensor, features: torch.Tensor):
        keyboard_mask = keyboard[..., -1] > 0
        mouse_mask = mouse[..., -1] > 0
        keyboard_lengths = keyboard_mask.sum(dim=1).clamp_min(1).cpu()
        packed = pack_padded_sequence(
            keyboard,
            keyboard_lengths,
            batch_first=True,
            enforce_sorted=False,
        )
        packed_out, _ = self.keyboard(packed)
        keyboard_out, _ = pad_packed_sequence(
            packed_out,
            batch_first=True,
            total_length=keyboard.shape[1],
        )
        keyboard_embedding = _masked_mean(keyboard_out, keyboard_mask)
        mouse_embedding = self.mouse(mouse, mouse_mask)
        feature_embedding = self.features(features)
        embedding = nn.functional.normalize(self.fusion(torch.cat([keyboard_embedding, mouse_embedding, feature_embedding], dim=-1)))
        return embedding, self.classifier(embedding)


def _key_code(value: str) -> float:
    digest = hashlib.blake2b(value.encode(), digest_size=2).digest()
    return int.from_bytes(digest, "big") / 65535.0


def session_sequences(session: dict[str, Any], key_length: int = 256, mouse_length: int = 512) -> tuple[np.ndarray, np.ndarray]:
    events = sorted((session.get("keyboard") or {}).get("events") or [], key=lambda e: e.get("press_ts", 0))
    keyboard = np.zeros((key_length, 6), dtype=np.float32)
    for index, event in enumerate(events[:key_length]):
        previous = events[index - 1] if index else event
        dwell = (event.get("release_ts") or event.get("press_ts", 0)) - event.get("press_ts", 0)
        iki = event.get("press_ts", 0) - previous.get("press_ts", 0)
        keyboard[index] = [_key_code(str(event.get("key_id", ""))), dwell / 500, iki / 1000, float(bool(event.get("shift_held"))), event.get("shift_hold_ms", 0) / 500, 1]
    points = (session.get("mouse") or {}).get("passive_points") or []
    mouse = np.zeros((mouse_length, 6), dtype=np.float32)
    for index, point in enumerate(points[:mouse_length]):
        previous = points[index - 1] if index else point
        dt = max(point.get("ts", 0) - previous.get("ts", 0), 1)
        dx = point.get("dx")
        dy = point.get("dy")
        if dx is None:
            dx = point.get("x", point.get("cursor_x", 0)) - previous.get(
                "x", previous.get("cursor_x", 0)
            )
        if dy is None:
            dy = point.get("y", point.get("cursor_y", 0)) - previous.get(
                "y", previous.get("cursor_y", 0)
            )
        mouse[index] = [dx / 100, dy / 100, dt / 100, np.hypot(dx, dy) / dt, point.get("pressure", 0), 1]
    return keyboard, mouse
