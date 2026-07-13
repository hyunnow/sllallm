#!/usr/bin/env python3
"""중복 실라버스 탐지 (HANDOFF §2). 전 코퍼스에서:
  - 파일 간 근사중복 클러스터 (MinHash Jaccard + 메타 지문)
  - 파일 내 다중 실라버스 문서

Usage:  python scripts/20_dedup.py [--jaccard 0.7] [--limit N]
산출: data/records/duplicates.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.dedup import (
    doc_signature, estimated_jaccard, intra_file_syllabus_count, metadata_key,
)
from syllabus_classifier.dedup.detect import filename_key
from syllabus_classifier.extract.normalize_doc import NormalizedDoc
from syllabus_classifier.extract.rule_fields import extract_rule_fields


class _Union:
    def __init__(self, items):
        self.p = {x: x for x in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jaccard", type=float, default=0.9,
                    help="순수 텍스트 근사중복 임계 (같은 과목 분반 0.96 vs 보일러플레이트 ≤0.62 분리선)")
    ap.add_argument("--meta-jaccard", type=float, default=0.85,
                    help="추출 메타 지문이 같을 때 요구하는 최소 텍스트 유사도 (한양대 웹추출 오병합 방지)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    norm_dir = resolve_path(load_config("data.yaml")["paths"]["normalized_dir"])
    files = sorted(norm_dir.glob("*.json"))
    if args.limit:
        files = files[: args.limit]

    docs = []            # (doc_id, sig, meta_key, filename_key, text_len)
    intra = []           # 파일 내 다중 실라버스
    for fp in files:
        doc = NormalizedDoc.from_dict(json.loads(fp.read_text(encoding="utf-8")))
        text = doc.full_text
        cnt, titles = intra_file_syllabus_count(text)
        if cnt >= 2:
            intra.append({"doc_id": doc.doc_id, "count": cnt, "titles": titles})
        sig = doc_signature(text)
        if sig is None:
            continue
        rule = extract_rule_fields(doc)
        mkey = metadata_key(rule.get("meta.school"),
                            rule.get("course.title_ko") or rule.get("course.title_en"),
                            rule.get("instructors.name"))
        docs.append((doc.doc_id, sig, mkey, filename_key(doc.doc_id), len(text)))

    # 파일 간: MinHash 밴딩으로 텍스트 근사중복 후보 축소 + 키(추출메타·파일명)
    # 버킷으로 텍스트가 갈라진 동일 강의(B3-025/031) 후보를 각각 만든 뒤 Jaccard 확정
    BANDS, ROWS = 12, 4               # 12*4 = 48 = _K
    buckets: dict = {}
    for idx, (_, sig, _, _, _) in enumerate(docs):
        for b in range(BANDS):
            band = tuple(sig[b * ROWS:(b + 1) * ROWS])
            buckets.setdefault((b, band), []).append(idx)
    meta_buckets: dict = {}
    fname_buckets: dict = {}
    for idx, (_, _, mkey, fkey, _) in enumerate(docs):
        if mkey:
            meta_buckets.setdefault(mkey, []).append(idx)
        if fkey:
            fname_buckets.setdefault(fkey, []).append(idx)

    uf = _Union(range(len(docs)))
    edges = 0
    checked = set()

    def consider(i, j):
        nonlocal edges
        if i == j or (i, j) in checked:
            return
        checked.add((i, j))
        jac = estimated_jaccard(docs[i][1], docs[j][1])
        same_fname = docs[i][3] and docs[i][3] == docs[j][3]
        same_meta = docs[i][2] and docs[i][2] == docs[j][2]
        # 엣지: (1) 거의 동일 텍스트(같은 과목 0.96 vs 다른 과목 보일러플레이트 ≤0.62)
        # (2) kocw 파일명 동일 (추출 갈라져도 — B3-025/031). 추출메타 경로는 한양대
        # 웹추출이 다른 과목에 같은(잘못된) 제목을 줘 오병합하므로 높은 유사도 요구.
        if jac >= args.jaccard or same_fname or (same_meta and jac >= args.meta_jaccard):
            uf.union(i, j)
            edges += 1

    for members in list(buckets.values()) + list(meta_buckets.values()) + list(fname_buckets.values()):
        if len(members) > 1:
            for a in range(len(members)):
                for b in range(a + 1, len(members)):
                    consider(*sorted((members[a], members[b])))

    clusters: dict = {}
    for idx in range(len(docs)):
        clusters.setdefault(uf.find(idx), []).append(idx)
    dup_clusters = []
    for members in clusters.values():
        if len(members) <= 1:
            continue
        # 사유: 파일명/추출 메타 키를 공유하면 같은 강의(진짜 중복), 아니면 순수
        # 텍스트 근사동일 = 웹추출 템플릿 껍데기(얇은 추출, 데이터 품질 이슈)
        fkeys = {docs[i][3] for i in members if docs[i][3]}
        mkeys = {docs[i][2] for i in members if docs[i][2]}
        same_course = (len(fkeys) == 1 and len(members) == sum(1 for i in members if docs[i][3])) \
            or (len(mkeys) == 1 and len(members) == sum(1 for i in members if docs[i][2]))
        dup_clusters.append({
            "reason": "same_course" if same_course else "template_near_identical",
            "docs": sorted([{"doc_id": docs[i][0], "text_len": docs[i][4], "meta_key": docs[i][2]}
                            for i in members], key=lambda d: -d["text_len"]),
        })
    dup_clusters.sort(key=lambda c: (c["reason"] != "same_course", -len(c["docs"])))

    same_course = [c for c in dup_clusters if c["reason"] == "same_course"]
    template = [c for c in dup_clusters if c["reason"] != "same_course"]
    print(f"docs {len(docs)} (텍스트 유효) | 후보쌍 검사 {len(checked)} | "
          f"근사중복 클러스터 {len(dup_clusters)} (같은 강의 {len(same_course)} / 템플릿 근사동일 {len(template)})")
    print("\n[같은 강의 = 진짜 중복 (파일명·메타 키 일치)]")
    for c in same_course[:10]:
        d = c["docs"]
        print(f"  [{len(d)}] " + " ≡ ".join(f"{x['doc_id'][:40]}({x['text_len']}자)" for x in d[:3])
              + (" …" if len(d) > 3 else ""))
    print(f"\n[템플릿 근사동일 = 얇은 웹추출 (본문 미포함, 데이터 품질) — 상위 6]")
    for c in template[:6]:
        d = c["docs"]
        print(f"  [{len(d)}] " + " ≡ ".join(f"{x['doc_id'][:40]}" for x in d[:2]) + " …")
    dup_docs = sum(len(c["docs"]) for c in dup_clusters)
    print(f"\n근사중복에 속한 문서 {dup_docs}건 → 유니크 {len(docs) - dup_docs + len(dup_clusters)}건")

    print(f"\n파일 내 다중 실라버스 의심 {len(intra)}건:")
    for d in intra[:10]:
        print(f"  {d['doc_id'][:46]}  ({d['count']}개): {', '.join(t[:16] for t in d['titles'][:4])}")

    out = resolve_path("data/records/duplicates.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"inter_file_clusters": dup_clusters, "intra_file_multi": intra,
         "params": {"jaccard": args.jaccard, "meta_jaccard": args.meta_jaccard}},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
