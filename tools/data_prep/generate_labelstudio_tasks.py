import argparse
import json
import random
import re
from pathlib import Path


FILENAME_RE = re.compile(r"^DART_(P\d+)_(.+)_(\d{14})_extracted\.txt$")
SECTION_RE = re.compile(r"^--- \[ 파일: (.+?) \] ---\s*$", re.MULTILINE)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate Label Studio task JSON from extracted DART text files."
    )
    parser.add_argument(
        "--text-dir",
        required=True,
        help="Directory containing *_extracted.txt files.",
    )
    parser.add_argument(
        "--pdf-dir",
        help="Optional directory containing *_rendered.pdf files.",
    )
    parser.add_argument(
        "--documents-root",
        default=r"C:\Users\hibou\Documents",
        help="Root directory configured for LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSON file path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Maximum number of tasks to export. Use 0 to export all tasks.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=80000,
        help="Maximum number of characters from each text file to embed.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling.",
    )
    parser.add_argument(
        "--balanced",
        action="store_true",
        help="Sample approximately balanced by P-label (P0, P1, ...).",
    )
    return parser.parse_args()


def to_local_files_url(path: Path, documents_root: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(documents_root.resolve())
    except ValueError:
        return None
    rel_str = rel.as_posix()
    return f"/data/local-files/?d={rel_str}"


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def iter_sections(raw_text: str):
    matches = list(SECTION_RE.finditer(raw_text))
    if not matches:
        yield {"section_file": "", "section_index": 1, "content": raw_text.strip()}
        return

    for idx, match in enumerate(matches, start=1):
        start = match.end()
        end = matches[idx].start() if idx < len(matches) else len(raw_text)
        content = raw_text[start:end].strip()
        if content:
            yield {
                "section_file": match.group(1).strip(),
                "section_index": idx,
                "content": content,
            }


def detect_title(lines: list[str]) -> str:
    title_specs = [
        ("자기주식취득결과보고서", ["자기주식취득결과보고서"]),
        ("자기주식처분결과보고서", ["자기주식처분결과보고서"]),
        ("주요사항보고서", ["주요사항보고서"]),
        ("사업보고서", ["사업보고서", "사업보고서"]),
        ("반기보고서", ["반기보고서"]),
        ("분기보고서", ["분기보고서"]),
        ("감사보고서", ["감사보고서", "감사보고서", "재무제표에대한감사보고서"]),
    ]
    for line in lines[:80]:
        normalized = compact(line)
        for canonical, patterns in title_specs:
            if any(pattern in normalized for pattern in patterns):
                return canonical
    return ""


def detect_primary_and_secondary(title: str, content: str) -> tuple[str, str]:
    normalized = compact(title + "\n" + content[:4000])

    if "자기주식취득결과보고서" in normalized:
        return "기타", "해당 없음"
    if "자기주식처분결과보고서" in normalized:
        return "자기주식처분결과보고서", "해당 없음"
    if "주요사항보고서" in normalized:
        secondary = "해당 없음"
        if "유상증자결정" in normalized:
            secondary = "유상증자결정"
        elif "정정" in normalized:
            secondary = "정정공시"
        elif "(" in title and ")" in title:
            secondary = "기타"
        return "주요사항보고서", secondary
    if "사업보고서" in normalized:
        return "사업보고서", "해당 없음"
    if "반기보고서" in normalized:
        return "반기보고서", "해당 없음"
    if "분기보고서" in normalized:
        return "분기보고서", "해당 없음"
    if "감사보고서" in normalized or "재무제표에대한감사보고서" in normalized:
        return "감사보고서", "해당 없음"
    return "기타", "해당 없음"


def detect_company(lines: list[str], company_hint: str) -> str:
    for idx, line in enumerate(lines[:120]):
        normalized = compact(line)
        if "회사명:" in normalized or "회사명:" in normalized.replace(" ", ""):
            if idx + 1 < len(lines):
                candidate = lines[idx + 1].strip()
                if candidate:
                    return candidate
        if normalized.startswith("회사명") and idx + 1 < len(lines):
            candidate = lines[idx + 1].strip()
            if candidate:
                return candidate
        if "주식회사" in line and len(line.strip()) <= 40:
            return line.strip()
        if line.strip().startswith("(주)") and len(line.strip()) <= 40:
            return line.strip()
    return company_hint


def detect_disclosure_title(lines: list[str], title: str) -> str:
    for line in lines[:40]:
        candidate = line.strip()
        normalized = compact(candidate)
        if not candidate or len(candidate) > 80:
            continue
        if any(
            token in normalized
            for token in [
                "주요사항보고서",
                "자기주식취득결과보고서",
                "자기주식처분결과보고서",
                "사업보고서",
                "반기보고서",
                "분기보고서",
                "감사보고서",
            ]
        ):
            return candidate
    if title:
        return title
    return lines[0].strip() if lines else ""


def build_predictions(primary: str, secondary: str, company_name: str, disclosure_title: str):
    result = []
    if primary:
        result.append(
            {
                "id": "pred-primary",
                "from_name": "document_type_primary",
                "to_name": "document_text",
                "type": "choices",
                "value": {"choices": [primary]},
            }
        )
    if secondary:
        result.append(
            {
                "id": "pred-secondary",
                "from_name": "document_type_secondary",
                "to_name": "document_text",
                "type": "choices",
                "value": {"choices": [secondary]},
            }
        )
    if company_name:
        result.append(
            {
                "id": "pred-company",
                "from_name": "company_name",
                "to_name": "document_text",
                "type": "textarea",
                "value": {"text": [company_name]},
            }
        )
    if disclosure_title:
        result.append(
            {
                "id": "pred-title",
                "from_name": "disclosure_title",
                "to_name": "document_text",
                "type": "textarea",
                "value": {"text": [disclosure_title]},
            }
        )
    if not result:
        return []
    return [{"model_version": "heuristic-v1", "result": result, "score": 0.7}]


def build_record(
    text_file: Path,
    pdf_dir: Path | None,
    documents_root: Path,
    max_chars: int,
):
    match = FILENAME_RE.match(text_file.name)
    if not match:
        return []

    p_label, company_hint, doc_id = match.groups()
    raw_text = text_file.read_text(encoding="utf-8", errors="ignore")

    pdf_url = None
    if pdf_dir:
        pdf_file = pdf_dir / f"{doc_id}_rendered.pdf"
        if pdf_file.exists():
            pdf_url = to_local_files_url(pdf_file, documents_root)

    records = []
    for section in iter_sections(raw_text):
        clean_text = section["content"].strip()
        truncated = clean_text[:max_chars]
        lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
        auto_title = detect_title(lines)
        auto_primary, auto_secondary = detect_primary_and_secondary(auto_title, clean_text)
        auto_company = detect_company(lines, company_hint)
        auto_disclosure_title = detect_disclosure_title(lines, auto_title)

        data = {
            "text": truncated,
            "file_name": text_file.name,
            "section_file": section["section_file"],
            "section_index": section["section_index"],
            "p_label_hint": p_label,
            "company_hint": company_hint,
            "doc_id": doc_id,
            "text_chars": len(clean_text),
            "is_truncated": len(clean_text) > len(truncated),
            "auto_primary_hint": auto_primary,
            "auto_secondary_hint": auto_secondary,
            "auto_company_hint": auto_company,
            "auto_title_hint": auto_disclosure_title,
        }
        if pdf_url:
            data["pdf_url"] = pdf_url

        records.append(
            {
                "data": data,
                "predictions": build_predictions(
                    auto_primary,
                    auto_secondary,
                    auto_company,
                    auto_disclosure_title,
                ),
            }
        )

    return records


def balanced_sample(records: list[dict], limit: int, seed: int) -> list[dict]:
    by_label: dict[str, list[dict]] = {}
    for record in records:
        label = record["data"]["p_label_hint"]
        by_label.setdefault(label, []).append(record)

    random.seed(seed)
    labels = sorted(by_label)
    for items in by_label.values():
        random.shuffle(items)

    sampled: list[dict] = []
    while len(sampled) < limit:
        progress = False
        for label in labels:
            items = by_label[label]
            if items and len(sampled) < limit:
                sampled.append(items.pop())
                progress = True
        if not progress:
            break
    return sampled


def main():
    args = parse_args()

    text_dir = Path(args.text_dir)
    pdf_dir = Path(args.pdf_dir) if args.pdf_dir else None
    documents_root = Path(args.documents_root)
    output = Path(args.output)

    files = sorted(text_dir.glob("*_extracted.txt"))
    records = []
    for text_file in files:
        built = build_record(text_file, pdf_dir, documents_root, args.max_chars)
        records.extend(built)

    limit = args.limit if args.limit and args.limit > 0 else len(records)

    if args.balanced:
        selected = balanced_sample(records, limit, args.seed)
    else:
        random.seed(args.seed)
        random.shuffle(records)
        selected = records[:limit]

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(selected, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"tasks: {len(selected)}")
    print(f"saved: {output}")


if __name__ == "__main__":
    main()
