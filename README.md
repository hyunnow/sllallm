# Syllabus Time-Candidate Classifier (sllallm)

A small, specialized model that classifies each **date/time candidate** found in
a university syllabus, so that only genuine **class meeting times** reach the
calendar. It is **not** a full "PDF in, JSON out" parser — it is the one piece
that stops the real, recurring failure:

> A syllabus says `연구실 및 면담시간 / Office Location&Hours: 월요일 22:00~23:00`.
> The old pipeline put that **office-hours** time into the calendar as a
> **class**. This model exists to filter exactly that out.

**Core principle:** putting a *wrong* schedule in is far worse than *missing* one.
So `class_schedule` **precision** is the top priority — above recall. When unsure,
we do **not** call something a class.

---

## What the model does (and doesn't)

- **Does:** for each time candidate, predict one of 8 classes and derive
  `include_in_class_schedule` (true only for `class_schedule`).
- **Doesn't:** convert period→time or week→date. That is external knowledge and
  is handled by **knowledge bases (KBs)**, never learned by the model.

Four processing mechanisms (master spec §1): **S**chema (null/array) · **M**odel
(kind classification) · **KB** (period/calendar lookup) · **R**ule + `needs_review`.

## Pipeline

```
document (PDF / scan / HWP)
  → normalize: text + tables + section titles   (Phase 1)
  → normalize surface notation                  (Phase 5 §5, deterministic)
  → extract ALL date/time candidates (rules)    (Phase 3, recall-first)
  → [★ classifier ★] label each candidate       (Phase 7; heuristic baseline today)
  → rule validator (safety net)                 (Phase 9)
  → KB resolve (period→time, week→date)         (§2)
  → class_schedule candidates only → calendar
```

## Data

- Real corpus: **~1026 files** across **8 institutions** (KAIST, NYU Stern,
  UNIST, YISS, Hanyang, KOCW, Gachon, …), **~99% PDF** (a few HWP/doc), **KO/EN
  mixed**. Lives in `실라버스 모음 폴더/` and is **git-ignored** (privacy + size).
- We train on **candidates, not documents**: ~1026 docs × 10–50 candidates each
  → tens of thousands of training samples.
- Performance is judged **only on a real holdout** (no augmentation), split by
  document id so nothing leaks (Phase 6).

## Labels (8)

`class_schedule` · `instructor_office_hours` · `ta_office_hours` · `exam_time` ·
`assignment_deadline` · `weekly_plan` · `policy_text` · `unknown`

Every date expression is first sorted into a **date_kind**: `absolute` ·
`relative` (→ KB) · `uncertain` (→ needs_review) · `recurring`.

## Repo layout

```
config/                 data + noise + train configs, and the two KBs
  period_timetables.yaml   KB1: (school, term_type) → period clock times
  academic_calendars.yaml  KB2: (school, year_term) → term start + holidays
data/edge_cases/registry.jsonl   U1–U6 + C1–C11 catalog (tests/aug/eval seed)
src/syllabus_classifier/
  common/     schema (labels, date_kind, records), config loader, seed
  normalize/  surface normalization (§5)          [done]
  extract/    doc normalization + candidate extractor (Phase 1, 3)
  kb/         period/calendar resolvers (§2)       [done]
  model/      classifier interface + heuristic baseline; encoder trainer (Phase 7)
  validator/  safety-net rules (Phase 9)           [done]
  noise/      surface augmentation (Phase 5)       [done]
  dataset/    candidate dataset build + group split (Phase 4, 6)
  label/      LLM-assisted labeling + review export (Phase 2)
  eval/       risk-aware metrics + confusion matrix (Phase 8)
scripts/      00_smoke_test.py + per-phase entrypoints
tests/        regression cases (Phase 8), normalize, KB resolver
```

## Quickstart

```bash
pip install -r requirements.txt          # minimal deterministic pipeline
python scripts/00_smoke_test.py          # end-to-end on synthetic data
pip install -e ".[dev]" && pytest        # regression + unit tests
```

The smoke test proves the flagship guardrail: the office-hours case is filtered
out of `class_schedule`, while a real class time is kept.

### Pipeline (Phase 1 → 7)

```bash
python scripts/01_normalize.py                 # docs -> text/tables (data/normalized)
python scripts/02_label.py --n 8000 --workers 6  # OpenAI-assisted labels (data/candidates)
python scripts/03_extract_candidates.py        # inspect candidates + heuristic labels
python scripts/04_build_dataset.py             # labels -> training examples (dataset.jsonl)
python scripts/06_split.py                     # leakage-proof group split by doc_id

# Phase 7 — train on Colab (GPU):
pip install -e ".[train]"
python scripts/07_train.py --config train.yaml # class-weighted/focal, real-holdout metrics
```

## Status

**Phase 0–2 complete.**
- **Phase 0** — repo scaffold, schema/KB contracts, deterministic core, heuristic
  baseline, green end-to-end smoke test.
- **Phase 1** — full corpus normalized (1026 docs → **7099 candidates**). Text
  PDFs via pdfplumber (976), HWP via `hwp5txt` (8). 39 scanned PDFs are flagged
  `needs_ocr` (EasyOCR on Colab); 3 legacy .doc/.docx logged unsupported. FP/recall
  hardening on real data: class_schedule needs a range/period or an explicit
  class-time field, killing export-timestamp and deadline false positives while
  recovering Korean "강의시간" start-times.
- **Phase 2** — OpenAI (`gpt-4o-mini`) assisted labeling. 968 candidates drafted;
  labels certified on the class_schedule boundary (no office-hours leaked into
  class; prose/timetable class times recovered vs the rule baseline). Review via
  `scripts/02_label.py` → `data/candidates/label_review.csv`.

### Next
- **Human spot-check** the label review (focus: the class_schedule filter).
- **Scale labeling** across the full 7099-candidate pool to build the training set.
- **Phase 4 → 6 → 7** — candidate dataset, group split, encoder training (Colab).
- **Colab OCR** for the 39 scanned PDFs (EasyOCR), then re-extract those docs.
- **KB coverage** — collect per-institution timetables/calendars to keep the
  `needs_review` rate low (KOCW spans many schools).

See `syllabus_classifier_claude_code_prompt.md` and
`syllabus_edge_cases_master_v2.md` for the full specification.
