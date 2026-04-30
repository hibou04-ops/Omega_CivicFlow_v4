"""
qa_dataset_integrity.py — Hyper-performance QC/QA pipeline for QLoRA datasets

Multi-process streaming validator across 8 dimensions:
  (1) JSON well-formedness
  (2) ChatML schema compliance
  (3) Role enumeration validity
  (4) Content non-emptiness
  (5) Korean language dominance (>=85% of CJK chars)
  (6) Chinese contamination flag
  (7) Cross-file deduplication (Blake2b fingerprint)
  (8) Composite weighted integrity score

Optimizations:
  - orjson (5x faster than stdlib json) with graceful fallback
  - Streaming line-by-line read (no full-file load)
  - Pre-compiled Unicode regex for CJK detection
  - ProcessPoolExecutor file-level parallelism (utilizes all CPU cores)
  - Blake2b 8-byte fingerprint (collision-safe for ~10^9 records)

Usage: python backend/tools/qa_dataset_integrity.py
"""
import os
import sys
import json
import re
import time
import hashlib
import multiprocessing as mp
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

# orjson — 5x faster JSON parsing if available, graceful fallback
try:
    import orjson
    def jload(b): return orjson.loads(b)
    JSON_BACKEND = "orjson"
except ImportError:
    def jload(b): return json.loads(b)
    JSON_BACKEND = "stdlib-json"

# Pre-compiled Unicode regex (Hangul / CJK Unified / Hiragana+Katakana)
RE_KO = re.compile(r'[\uac00-\ud7af]')
RE_ZH = re.compile(r'[\u4e00-\u9fff]')
RE_JP = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')

VALID_ROLES = frozenset({'system', 'user', 'assistant'})


def extract_text(content):
    """Extract concatenated text from message.content (str | list[dict])."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get('type') == 'text':
                t = c.get('text')
                if isinstance(t, str):
                    parts.append(t)
        return ' '.join(parts)
    return ''


def check_record(line_bytes):
    """Per-record integrity assertions. Returns dict of binary flags."""
    r = {
        'json_ok': 0, 'schema_ok': 0, 'roles_ok': 0,
        'nonempty_ok': 0, 'ko_dominant': 0, 'zh_contaminated': 0,
        'hash': None, 'chars': 0,
    }
    try:
        rec = jload(line_bytes)
    except Exception:
        return r
    r['json_ok'] = 1

    if not isinstance(rec, dict):
        return r

    # Accept both ChatML (messages) and instruction format (input/output)
    msgs = rec.get('messages')
    if isinstance(msgs, list) and msgs:
        r['schema_ok'] = 1
        roles_ok = True
        parts = []
        for m in msgs:
            if not isinstance(m, dict):
                roles_ok = False
                continue
            if m.get('role') not in VALID_ROLES:
                roles_ok = False
            parts.append(extract_text(m.get('content', '')))
        if roles_ok:
            r['roles_ok'] = 1
        text = ' '.join(p for p in parts if p)
    elif 'input' in rec and 'output' in rec:
        # Legacy instruction tuning format
        r['schema_ok'] = 1
        r['roles_ok'] = 1  # No roles to validate
        text = f"{rec.get('input', '')} {rec.get('output', '')}"
    else:
        return r

    r['chars'] = len(text)
    if text.strip():
        r['nonempty_ok'] = 1

    if text:
        ko = len(RE_KO.findall(text))
        zh = len(RE_ZH.findall(text))
        jp = len(RE_JP.findall(text))
        cjk = ko + zh + jp
        if cjk > 0 and ko / cjk >= 0.85:
            r['ko_dominant'] = 1
        if zh >= 50:
            r['zh_contaminated'] = 1
        r['hash'] = hashlib.blake2b(
            text.encode('utf-8', errors='ignore'), digest_size=8
        ).digest()

    return r


def process_file(filepath):
    """Stream a JSONL file. Returns aggregated metrics + hash set."""
    m = defaultdict(int)
    hashes = set()
    char_total = 0
    n = 0
    t0 = time.perf_counter()
    size = os.path.getsize(filepath)

    with open(filepath, 'rb') as f:
        for line in f:
            if not line.strip():
                continue
            n += 1
            r = check_record(line)
            for k in ('json_ok', 'schema_ok', 'roles_ok',
                      'nonempty_ok', 'ko_dominant', 'zh_contaminated'):
                m[k] += r[k]
            char_total += r['chars']
            if r['hash'] is not None:
                hashes.add(r['hash'])

    elapsed = time.perf_counter() - t0
    return {
        'file': str(filepath),
        'name': Path(filepath).name,
        'records': n,
        'size_bytes': size,
        'chars': char_total,
        'elapsed_sec': elapsed,
        'metrics': dict(m),
        'hashes': hashes,
    }


def main():
    # 환경변수 OMEGA_DATASET_DIR 로 override, 기본값은 프로젝트 루트의 ./datasets
    import os
    default_dir = Path(__file__).resolve().parent.parent.parent / "datasets"
    DATASET_DIR = Path(os.environ.get("OMEGA_DATASET_DIR", str(default_dir)))
    files = sorted(DATASET_DIR.glob("*.jsonl"))
    if not files:
        print(f"[ERROR] No .jsonl files found at {DATASET_DIR}")
        sys.exit(1)

    workers = min(len(files), mp.cpu_count())
    print("=" * 80)
    print("  QLoRA Dataset Integrity QC/QA  -  Hyper-Performance Pipeline")
    print("=" * 80)
    print(f"  Target dir : {DATASET_DIR}")
    print(f"  Files      : {len(files)}")
    print(f"  Workers    : {workers}")
    print(f"  JSON engine: {JSON_BACKEND}")
    print("=" * 80)

    overall_t0 = time.perf_counter()

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_file, str(f)): f for f in files}
        results = []
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            print(f"  [done] {r['name']:<34} {r['records']:>9,} rec  "
                  f"{r['elapsed_sec']:>6.2f}s  "
                  f"{r['size_bytes']/1e6/r['elapsed_sec']:>6.1f} MB/s")

    overall_elapsed = time.perf_counter() - overall_t0

    # ---- Aggregate ----
    total_records = sum(r['records'] for r in results)
    total_size = sum(r['size_bytes'] for r in results)
    total_chars = sum(r['chars'] for r in results)

    grand = defaultdict(int)
    for r in results:
        for k, v in r['metrics'].items():
            grand[k] += v

    # Cross-file dedup
    all_hashes = set()
    for r in results:
        all_hashes.update(r['hashes'])
    unique_total = len(all_hashes)
    duplicate_total = total_records - unique_total

    # ---- Per-file table ----
    print()
    print("Per-file integrity:")
    print(f"  {'file':<35} {'records':>9} {'json%':>8} {'schema%':>9} "
          f"{'ko%':>7} {'zh-flag':>8}")
    print("  " + "-" * 78)
    for r in sorted(results, key=lambda x: x['name']):
        n = r['records']
        if n == 0:
            continue
        m = r['metrics']
        print(f"  {r['name']:<35} {n:>9,} "
              f"{100*m['json_ok']/n:>7.3f}% "
              f"{100*m['schema_ok']/n:>8.3f}% "
              f"{100*m['ko_dominant']/n:>6.2f}% "
              f"{m['zh_contaminated']:>8,}")

    # ---- Aggregate report ----
    p = lambda k: 100 * grand[k] / total_records if total_records else 0
    print()
    print("=" * 80)
    print("  AGGREGATE INTEGRITY REPORT")
    print("=" * 80)
    print(f"  Total records       : {total_records:>14,}")
    print(f"  Total size          : {total_size/1e9:>14.3f} GB")
    print(f"  Total characters    : {total_chars:>14,}")
    print(f"  Wall-clock time     : {overall_elapsed:>14.3f} sec")
    print(f"  Throughput          : {total_size/1e6/overall_elapsed:>14.2f} MB/sec")
    print(f"  Records/sec         : {total_records/overall_elapsed:>14,.0f}")
    print()
    print("  Integrity Dimensions:")
    print(f"    (1) JSON well-formed      : {p('json_ok'):>8.4f}%")
    print(f"    (2) ChatML schema valid   : {p('schema_ok'):>8.4f}%")
    print(f"    (3) Role enum valid       : {p('roles_ok'):>8.4f}%")
    print(f"    (4) Content non-empty     : {p('nonempty_ok'):>8.4f}%")
    print(f"    (5) Korean dominant >=85% : {p('ko_dominant'):>8.4f}%")
    print()
    print("  Anomaly Detection:")
    zh_pct = 100*grand['zh_contaminated']/total_records if total_records else 0
    dup_pct = 100*duplicate_total/total_records if total_records else 0
    print(f"    Chinese contaminated    : {grand['zh_contaminated']:>10,} "
          f"({zh_pct:.4f}%)")
    print(f"    Duplicate (cross-file)  : {duplicate_total:>10,} "
          f"({dup_pct:.4f}%)")
    print(f"    Unique fingerprints     : {unique_total:>10,}")
    print()

    # Composite integrity score (weighted)
    weights = {
        'json_ok':      0.30,
        'schema_ok':    0.25,
        'roles_ok':     0.20,
        'nonempty_ok':  0.15,
        'ko_dominant':  0.10,
    }
    composite = (
        sum(weights[k] * (grand[k] / total_records) for k in weights)
        if total_records else 0
    )
    composite_pct = 100 * composite

    print("=" * 80)
    print(f"  *** COMPOSITE INTEGRITY SCORE :  {composite_pct:.4f} %  ***")
    print("=" * 80)

    # ---- Persist JSON report ----
    report = {
        "target_dir": str(DATASET_DIR),
        "files_scanned": len(files),
        "total_records": total_records,
        "total_size_bytes": total_size,
        "total_size_gb": round(total_size/1e9, 4),
        "total_characters": total_chars,
        "wall_clock_sec": round(overall_elapsed, 4),
        "throughput_mb_per_sec": round(total_size/1e6/overall_elapsed, 2),
        "records_per_sec": round(total_records/overall_elapsed, 0),
        "json_backend": JSON_BACKEND,
        "workers": workers,
        "integrity_pct": {
            "json_well_formed":    round(p('json_ok'), 4),
            "chatml_schema_valid": round(p('schema_ok'), 4),
            "roles_valid":         round(p('roles_ok'), 4),
            "content_nonempty":    round(p('nonempty_ok'), 4),
            "korean_dominant":     round(p('ko_dominant'), 4),
            "composite_score":     round(composite_pct, 4),
        },
        "anomalies": {
            "chinese_contaminated": grand['zh_contaminated'],
            "chinese_contaminated_pct": round(zh_pct, 4),
            "duplicate_records": duplicate_total,
            "duplicate_pct": round(dup_pct, 4),
            "unique_fingerprints": unique_total,
        },
        "per_file": [
            {
                "name": r['name'],
                "records": r['records'],
                "size_bytes": r['size_bytes'],
                "elapsed_sec": round(r['elapsed_sec'], 3),
                "metrics_pct": (
                    {k: round(100*v/r['records'], 4)
                     for k, v in r['metrics'].items()}
                    if r['records'] else {}
                ),
            }
            for r in sorted(results, key=lambda x: x['name'])
        ],
    }
    out_path = Path(__file__).resolve().parent.parent.parent / "dataset_qc_report.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    print(f"\n  [saved] {out_path}")


if __name__ == "__main__":
    main()
