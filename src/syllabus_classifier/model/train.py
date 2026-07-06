"""Encoder classifier training (Phase 7). Targets Colab (GPU + torch + transformers).

Design decisions that follow the product's risk profile:
  - input = "candidate_text [SEP] section/row/col [SEP] nearby text" (config train.yaml)
  - class imbalance (class_schedule ~20%, policy_text <1%): class-weighted or focal
    loss so rare/critical classes are not drowned out.
  - class_schedule precision is paramount: at inference we apply a conservative
    confidence threshold — if the top prediction is class_schedule but below the
    threshold, we back off to the runner-up. When unsure, don't say class.
  - performance is reported on the REAL HOLDOUT (test split) with the risk-aware
    metrics from eval.metrics, plus the confusion matrix.

torch/transformers are imported lazily inside functions so the rest of the
package still imports on a machine without them (e.g. the extraction box).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Optional

from ..common.config import load_config, resolve_path
from ..common.schema import ALL_LABELS, include_in_class_schedule
from ..eval.metrics import evaluate

LABEL2ID = {l: i for i, l in enumerate(ALL_LABELS)}
ID2LABEL = {i: l for l, i in LABEL2ID.items()}
CLASS_ID = LABEL2ID["class_schedule"]


# --- data (testable without torch) ----------------------------------------
def load_split(path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def compute_class_weights(rows: list[dict]) -> list[float]:
    """Inverse-frequency weights aligned to ALL_LABELS (missing labels -> weight 1)."""
    counts = Counter(r["label"] for r in rows)
    total = sum(counts.values())
    n_classes = len(ALL_LABELS)
    weights = []
    for lab in ALL_LABELS:
        c = counts.get(lab, 0)
        weights.append(total / (n_classes * c) if c else 1.0)
    return weights


def predict_with_threshold(probs, threshold: float):
    """Argmax, but demote a low-confidence class_schedule to its runner-up
    (precision > recall). `probs` is a 2-D array [n, num_labels]."""
    import numpy as np

    ids = probs.argmax(axis=1)
    out = []
    for row, top in zip(probs, ids):
        if top == CLASS_ID and row[CLASS_ID] < threshold:
            order = row.argsort()[::-1]
            top = int(order[1])  # runner-up
        out.append(int(top))
    return out


# --- training (needs torch + transformers) ---------------------------------
def train(config_name: str = "train.yaml", data_dir: Optional[str] = None, out_dir: Optional[str] = None) -> dict:
    import numpy as np
    import torch
    import torch.nn as nn
    from datasets import Dataset
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    cfg = load_config(config_name)
    data_cfg = load_config("data.yaml")
    splits_dir = Path(data_dir) if data_dir else resolve_path(data_cfg["paths"]["splits_dir"])
    out_dir = Path(out_dir) if out_dir else resolve_path("checkpoints") / "encoder"
    out_dir.mkdir(parents=True, exist_ok=True)

    mcfg, tcfg = cfg["model"], cfg["training"]
    encoder = mcfg["encoder"]
    max_len = mcfg["max_length"]
    threshold = tcfg["class_schedule_confidence_threshold"]

    train_rows = load_split(splits_dir / "train.jsonl")
    val_rows = load_split(splits_dir / "val.jsonl")
    test_rows = load_split(splits_dir / "test.jsonl")
    print(f"train={len(train_rows)} val={len(val_rows)} test={len(test_rows)}")

    tokenizer = AutoTokenizer.from_pretrained(encoder)

    def to_ds(rows):
        return Dataset.from_dict({
            "text": [r["input_text"] for r in rows],
            "label": [LABEL2ID[r["label"]] for r in rows],
        })

    def tok(batch):
        return tokenizer(batch["text"], truncation=True, max_length=max_len)

    ds_train = to_ds(train_rows).map(tok, batched=True)
    ds_val = to_ds(val_rows).map(tok, batched=True)
    ds_test = to_ds(test_rows).map(tok, batched=True)

    model = AutoModelForSequenceClassification.from_pretrained(
        encoder, num_labels=len(ALL_LABELS), id2label=ID2LABEL, label2id=LABEL2ID,
    )

    class_weights = torch.tensor(compute_class_weights(train_rows), dtype=torch.float)
    gamma = tcfg.get("focal_gamma", 2.0)
    loss_kind = tcfg.get("loss", "focal")

    class WeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, **kw):
            labels = inputs.pop("labels")
            outputs = model(**inputs)
            logits = outputs.logits
            w = class_weights.to(logits.device)
            if loss_kind == "focal":
                ce = nn.functional.cross_entropy(logits, labels, weight=w, reduction="none")
                pt = torch.exp(-ce)
                loss = ((1 - pt) ** gamma * ce).mean()
            elif loss_kind == "weighted_ce":
                loss = nn.functional.cross_entropy(logits, labels, weight=w)
            else:
                loss = nn.functional.cross_entropy(logits, labels)
            return (loss, outputs) if return_outputs else loss

    def compute_metrics(eval_pred):
        logits, labels = eval_pred
        probs = torch.softmax(torch.tensor(logits), dim=1).numpy()
        pred_ids = predict_with_threshold(probs, threshold)
        y_true = [ID2LABEL[int(i)] for i in labels]
        y_pred = [ID2LABEL[i] for i in pred_ids]
        m = evaluate(y_true, y_pred)
        return {
            "class_precision": m["class_schedule_precision"],
            "class_recall": m["class_schedule_recall"],
            "office_to_class": m["office_hours_to_class_schedule_rate"],
            "macro_f1": m["macro_f1"],
        }

    args = TrainingArguments(
        output_dir=str(out_dir),
        num_train_epochs=tcfg["epochs"],
        per_device_train_batch_size=tcfg["batch_size"],
        per_device_eval_batch_size=tcfg["batch_size"],
        learning_rate=float(tcfg["lr"]),
        weight_decay=tcfg["weight_decay"],
        warmup_ratio=tcfg["warmup_ratio"],
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="class_precision",
        greater_is_better=True,
        logging_steps=50,
        seed=cfg.get("seed", 42),
    )

    from transformers import DataCollatorWithPadding
    trainer = WeightedTrainer(
        model=model, args=args,
        train_dataset=ds_train, eval_dataset=ds_val,
        tokenizer=tokenizer, data_collator=DataCollatorWithPadding(tokenizer),
        compute_metrics=compute_metrics,
    )
    trainer.train()

    # --- REAL HOLDOUT evaluation (spec Phase 8: judge here only) ---
    pred = trainer.predict(ds_test)
    probs = torch.softmax(torch.tensor(pred.predictions), dim=1).numpy()
    pred_ids = predict_with_threshold(probs, threshold)
    y_true = [ID2LABEL[int(i)] for i in pred.label_ids]
    y_pred = [ID2LABEL[i] for i in pred_ids]
    holdout = evaluate(y_true, y_pred)

    trainer.save_model(str(out_dir / "best"))
    tokenizer.save_pretrained(str(out_dir / "best"))
    (out_dir / "holdout_metrics.json").write_text(json.dumps(holdout, ensure_ascii=False, indent=2))

    print("\n=== REAL HOLDOUT (test) ===")
    print(f"  class_schedule precision : {holdout['class_schedule_precision']:.3f}")
    print(f"  class_schedule recall    : {holdout['class_schedule_recall']:.3f}")
    print(f"  office->class rate       : {holdout['office_hours_to_class_schedule_rate']:.3f}")
    print(f"  macro F1                 : {holdout['macro_f1']:.3f}")
    return holdout


if __name__ == "__main__":
    train()
