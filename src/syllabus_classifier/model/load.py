"""분류기 선택 한 곳 (로컬 모델 배선). 'heuristic' 또는 체크포인트 경로를 받아
Classifier를 만든다. 임계값을 안 주면 train.yaml 값(현재 0.50)을 쓴다 — 스크립트마다
임계값이 어긋나지 않게 단일 소스."""
from __future__ import annotations

from typing import Optional

from ..common.config import load_config
from .infer import Classifier, EncoderClassifier, HeuristicClassifier


def config_threshold() -> float:
    return float(load_config("train.yaml")["training"]["class_schedule_confidence_threshold"])


def load_classifier(model: str = "heuristic", threshold: Optional[float] = None) -> Classifier:
    """model='heuristic' → 규칙 기반(기본, 체크포인트 불필요).
    model=<dir>          → 그 체크포인트의 EncoderClassifier (torch/transformers 필요)."""
    if model in (None, "", "heuristic"):
        return HeuristicClassifier()
    return EncoderClassifier(model, threshold=threshold if threshold is not None else config_threshold())
