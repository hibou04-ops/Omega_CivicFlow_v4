# ============================================================
# 📦 AI Hub 데이터 → 학습용 JSONL 변환 스크립트 (정확한 버전)
#
# 지원 데이터셋:
#   1. 민간 민원 상담 LLM 사전학습 및 Instruction Tuning 데이터
#      - instructions[].data[]{instruction, input, output} 구조
#   2. 금융, 법률 문서 기계독해 데이터
#      - data[].paragraphs[].{context, qas[]{question, answers}} 구조
#
# 출력: Qwen2.5 / Llama3 SFTTrainer용 JSONL (messages 포맷)
# ============================================================

import os
import json
import zipfile
import glob
from pathlib import Path

# ── 설정 ────────────────────────────────────────────────────
DATASET1_DIR = r"C:\Users\hibou\Downloads\23.민간 민원 상담 LLM 사전학습 및 Instruction Tuning 데이터\3.개방데이터\1.데이터"
DATASET2_DIR = r"C:\Users\hibou\Downloads\151.금융, 법률 문서 기계독해 데이터\01-1.정식개방데이터"

OUTPUT_DIR  = r"C:\Users\hibou\Omega_CivicFlow_v3\datasets"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "civicflow_train.jsonl")
VALID_FILE  = os.path.join(OUTPUT_DIR, "civicflow_valid.jsonl")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── 시스템 프롬프트 ──────────────────────────────────────────
SYSTEM_PROMPT = "너는 한국어 금융·법률 문서를 분석하고, 요약하며, 질문에 답하는 전문 어시스턴트다."


# ══════════════════════════════════════════════════════════
# Dataset 0: didi0di/finance-legal-mrc-chat-template
#   tableqa_base64 → 텍스트 전용 변환 (이미지 제거)
#   messages 구조: [{role, content:[{type,text/image}]}]
# ══════════════════════════════════════════════════════════

def load_didi0di_text(split: str = "train") -> list:
    """로컬 Arrow 파일에서 didi0di 데이터를 텍스트 전용으로 변환 (오프라인 동작)"""
    LOCAL_PATH = r"C:\Users\hibou\Omega_CivicFlow DateSet\tableqa_processed"
    try:
        from datasets import load_from_disk
    except ImportError:
        print("  ⚠️ datasets 없음: pip install datasets")
        return []

    print(f"  📂 로컬 Arrow 로드: {LOCAL_PATH} ({split})...")
    try:
        ds_dict = load_from_disk(LOCAL_PATH)
        raw = ds_dict[split]
    except Exception as e:
        print(f"  ❌ 로컬 로드 실패: {e}")
        return []

    samples = []
    for item in raw:
        text_messages = []
        for msg in item.get("messages", []):
            role    = msg.get("role", "")
            content = msg.get("content", [])

            if isinstance(content, str):
                if content.strip():
                    text_messages.append({"role": role, "content": content.strip()})
                continue

            # type=="text" 항목만 추출, type=="image" 제외
            text_parts = [
                p.get("text", "").strip()
                for p in content
                if p.get("type") == "text" and p.get("text", "").strip()
            ]
            combined = "\n".join(text_parts).strip()
            if combined:
                text_messages.append({"role": role, "content": combined})

        has_assistant = any(m["role"] == "assistant" for m in text_messages)
        if not has_assistant:
            continue
        if not any(m["role"] == "system" for m in text_messages):
            text_messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

        samples.append({"messages": text_messages})

    print(f"  ✅ didi0di {split}: {len(samples):,}개")
    return samples


# ── 유틸: zip 안 JSON 파일 읽기 ─────────────────────────────
def read_jsons_from_zip(zip_path: str):
    results = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            entries = [e for e in zf.namelist()
                       if e.endswith('.json') and '__MACOSX' not in e]
            for entry in entries:
                with zf.open(entry) as f:
                    try:
                        data = json.load(f)
                        results.append(data)
                    except Exception as e:
                        print(f"  ⚠️ JSON 파싱 실패: {entry} - {e}")
    except Exception as e:
        print(f"  ❌ ZIP 열기 실패: {zip_path} - {e}")
    return results


# ══════════════════════════════════════════════════════════
# Dataset 1: 민간 민원 상담 LLM Instruction Tuning 데이터
# 구조: list of {consulting_content, consulting_category,
#                instructions: [{tuning_type, data: [{instruction, input, output}]}]}
# ══════════════════════════════════════════════════════════

def convert_dataset1(data: list) -> list:
    """
    instructions 필드 안의 실제 instruction tuning 데이터를 사용.
    각 항목에 instruction(지시문) + input(상담 내용) → user
    output → assistant
    """
    samples = []
    for item in data:
        instr_groups = item.get('instructions', [])
        for group in instr_groups:
            for d in group.get('data', []):
                instruction = d.get('instruction', '').strip()
                inp         = d.get('input', '').strip()
                output      = d.get('output', '').strip()

                if not instruction or not inp or not output:
                    continue

                user_content = f"{instruction}\n\n[상담 내용]\n{inp}"
                samples.append({
                    "messages": [
                        {"role": "system",    "content": SYSTEM_PROMPT},
                        {"role": "user",      "content": user_content},
                        {"role": "assistant", "content": output}
                    ]
                })
    return samples


# ══════════════════════════════════════════════════════════
# Dataset 2: 금융, 법률 문서 기계독해 데이터
# 구조: {Dataset: ..., data: [{doc_id, doc_title, paragraphs:
#         [{context, qas: [{question, answers:[{text}]}]}]}]}
# ══════════════════════════════════════════════════════════

def convert_dataset2(data: dict) -> list:
    """
    paragraphs의 context + qas의 question → user
    answers[0].text → assistant
    """
    samples = []
    docs = data.get('data', [])
    for doc in docs:
        doc_title = doc.get('doc_title', '')
        for para in doc.get('paragraphs', []):
            context = para.get('context', '').strip()
            for qa in para.get('qas', []):
                question = qa.get('question', '').strip()
                answers  = qa.get('answers', [])
                # answers가 없거나 빈 경우 skip (impossible 문제 등)
                if not answers:
                    continue
                answer = answers[0].get('text', '').strip()
                if not question or not answer or not context:
                    continue

                user_content = (
                    f"[문서 제목]\n{doc_title}\n\n"
                    f"[문서 내용]\n{context}\n\n"
                    f"[질문]\n{question}"
                )
                samples.append({
                    "messages": [
                        {"role": "system",    "content": SYSTEM_PROMPT},
                        {"role": "user",      "content": user_content},
                        {"role": "assistant", "content": answer}
                    ]
                })
    return samples


# ── ZIP 파일 처리 라우터 ─────────────────────────────────────
def process_zip(zip_path: str, dataset_num: int) -> list:
    all_samples = []
    json_list = read_jsons_from_zip(zip_path)
    name = os.path.basename(zip_path)
    print(f"  📂 {name}: {len(json_list)}개 JSON 파일", end='')

    for data in json_list:
        if dataset_num == 1:
            # Dataset 1: list 구조
            items = data if isinstance(data, list) else [data]
            samples = convert_dataset1(items)
        else:
            # Dataset 2: dict {Dataset, data} 구조
            samples = convert_dataset2(data)
        all_samples.extend(samples)

    print(f" → {len(all_samples)}개 샘플")
    return all_samples


# ── 메인 실행 ───────────────────────────────────────────────
def main():
    train_samples = []
    valid_samples = []

    # [0] didi0di tableqa (텍스트 전용)
    print(f"\n{'='*55}")
    print("📁 [0] didi0di/finance-legal-mrc-chat-template (텍스트 전용)")
    print(f"{'='*55}")
    train_samples.extend(load_didi0di_text("train"))
    valid_samples.extend(load_didi0di_text("test"))

    # [1] AI Hub 민원 상담 / [2] 금융법률 MRC
    configs = [
        (DATASET1_DIR, "민원 상담 LLM", 1),
        (DATASET2_DIR, "금융·법률 MRC", 2),
    ]

    for dataset_dir, label, ds_num in configs:
        print(f"\n{'='*55}")
        print(f"📁 [{ds_num}] {label} 처리 중...")
        print(f"{'='*55}")

        for split, out_list in [("Training", train_samples), ("Validation", valid_samples)]:
            split_dir = os.path.join(dataset_dir, split, "02.라벨링데이터")
            if not os.path.exists(split_dir):
                print(f"  ⚠️ 경로 없음: {split_dir}")
                continue

            zip_files = list(set(
                glob.glob(os.path.join(split_dir, "**", "*.zip"), recursive=True) +
                glob.glob(os.path.join(split_dir, "*.zip"))
            ))
            print(f"\n  [{split}] ZIP {len(zip_files)}개")
            for zf in sorted(zip_files):
                samples = process_zip(zf, ds_num)
                out_list.extend(samples)

        print(f"\n  ✅ {label} 완료 — Train: {len(train_samples):,}, Valid: {len(valid_samples):,}")

    # JSONL 저장
    for samples, path, tag in [
        (train_samples, OUTPUT_FILE, "Train"),
        (valid_samples, VALID_FILE,  "Valid"),
    ]:
        with open(path, 'w', encoding='utf-8') as f:
            for s in samples:
                f.write(json.dumps(s, ensure_ascii=False) + '\n')
        print(f"\n✅ {tag} 저장 완료: {path} ({len(samples):,}개)")

    print(f"\n🎉 전체 완료!")
    print(f"   Train: {len(train_samples):,}개")
    print(f"   Valid:  {len(valid_samples):,}개")
    print(f"   저장:  {OUTPUT_DIR}")

    if train_samples:
        print("\n── 샘플 미리보기 ──────────────────────────────")
        for msg in train_samples[0]['messages']:
            print(f"[{msg['role']}] {msg['content'][:120]}")


if __name__ == "__main__":
    main()
