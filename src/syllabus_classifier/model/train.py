"""Encoder classifier training (Phase 7).

Recommended: an encoder-based classifier (klue/roberta-base for Korean, or
xlm-roberta-base for mixed KO/EN). Input:
  candidate_text [SEP] section_title / row_label [SEP] nearby_text
Output: 8-way class + derived include_in_class_schedule.

Imbalance handling (class_schedule false positives are catastrophic): focal loss
or class weights, plus a high confidence threshold for class_schedule so the
model stays conservative (spec Phase 7).

STATUS: skeleton. Requires transformers + torch (see pyproject [train] extra)
and the Phase 4 dataset. The trained model exposes the same `Classifier.predict`
interface as HeuristicClassifier so the rest of the pipeline is unchanged.
"""
from __future__ import annotations

from ..common.config import load_config


def train(config_name: str = "train.yaml") -> None:
    cfg = load_config(config_name)
    raise NotImplementedError(
        "Phase 7: implement encoder fine-tuning with transformers once the "
        f"Phase 4 dataset exists. Loaded config: encoder={cfg['model']['encoder']}."
    )
