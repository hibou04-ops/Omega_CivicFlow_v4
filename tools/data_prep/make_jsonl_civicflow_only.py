# ============================================================
# 📦 CivicFlow DateSet 전용 VL JSONL 생성
# 데이터: C:\Users\hibou\Omega_CivicFlow DateSet (didi0di tableqa)
# 이미지(base64) + 텍스트 → Qwen2.5-VL 학습용 JSONL
# ============================================================

import os
import json
import base64

LOCAL_PATH   = r"C:\Users\hibou\Omega_CivicFlow DateSet\tableqa_processed"
OUTPUT_DIR   = r"C:\Users\hibou\Omega_CivicFlow_v3\datasets"
OUTPUT_TRAIN = os.path.join(OUTPUT_DIR, "civicflow_only_train.jsonl")
OUTPUT_VALID = os.path.join(OUTPUT_DIR, "civicflow_only_valid.jsonl")

os.makedirs(OUTPUT_DIR, exist_ok=True)

SYSTEM_PROMPT = (
    "너는 한국어 금융·법률 문서의 표(table)를 분석하고 "
    "정확하게 질문에 답변하는 전문 어시스턴트다."
)

def b64str_to_data_uri(b64: str, mime: str = "png") -> str:
    if b64.startswith("data:"):
        return b64
    return f"data:image/{mime};base64,{b64}"

LOCAL_DICT_PATH  = r"C:\Users\hibou\Omega_CivicFlow DateSet\tableqa_processed"
TRAIN_ARROW_PATH = r"C:\Users\hibou\Omega_CivicFlow DateSet\tableqa_processed\train"
TEST_ARROW_PATH  = r"C:\Users\hibou\Omega_CivicFlow DateSet\tableqa_processed\test"


def read_arrow_files(arrow_dir: str) -> list:
    """PyArrow로 .arrow 파일 직접 읽기 (datasets 버전 무관)"""
    import pyarrow as pa
    import pyarrow.ipc as ipc
    import glob

    arrow_files = sorted(glob.glob(os.path.join(arrow_dir, "*.arrow")))
    if not arrow_files:
        raise FileNotFoundError(f"Arrow 파일 없음: {arrow_dir}")

    tables = []
    for path in arrow_files:
        with open(path, "rb") as f:
            reader = ipc.open_file(f)
            tables.append(reader.read_all())

    combined = pa.concat_tables(tables)
    return combined.to_pylist()


def load_split(split: str) -> list:
    """split 데이터를 list of dict 형태로 반환"""
    arrow_dir = TRAIN_ARROW_PATH if split == "train" else TEST_ARROW_PATH

    # 방법 1: HF datasets load_from_disk
    try:
        from datasets import load_from_disk
        ds_dict = load_from_disk(LOCAL_DICT_PATH)
        rows = [dict(item) for item in ds_dict[split]]
        print(f"  ✅ HF datasets로 로드 ({split}): {len(rows):,}개")
        return rows
    except Exception as e1:
        print(f"  ⚠️ load_from_disk 실패 ({e1}), PyArrow 직접 읽기 시도...")

    # 방법 2: PyArrow 직접 읽기
    try:
        rows = read_arrow_files(arrow_dir)
        print(f"  ✅ PyArrow 직접 로드 ({split}): {len(rows):,}개")
        return rows
    except Exception as e2:
        print(f"  ❌ PyArrow 읽기도 실패: {e2}")
        return []


def convert_split(split: str) -> list:
    print(f"\n  📂 {split} 데이터 로딩...")
    rows = load_split(split)
    samples = []

    for item in rows:
        converted = [{"role": "system", "content": SYSTEM_PROMPT}]

        for msg in item.get("messages", []):
            role    = msg.get("role", "")
            content = msg.get("content", [])

            if isinstance(content, str):
                if content.strip():
                    converted.append({"role": role, "content": content.strip()})
                continue

            new_parts = []
            for part in content:
                ptype = part.get("type", "")
                if ptype == "text":
                    text = part.get("text", "").strip()
                    if text:
                        new_parts.append({"type": "text", "text": text})
                elif ptype == "image":
                    b64 = part.get("base64", "")
                    if b64:
                        uri = b64str_to_data_uri(b64, "png")
                        new_parts.append({"type": "image_url", "image_url": {"url": uri}})

            if new_parts:
                converted.append({"role": role, "content": new_parts})

        if any(m["role"] == "assistant" for m in converted):
            samples.append({"messages": converted})

    print(f"  ✅ {split}: {len(samples):,}개")
    return samples


def main():
    print("=" * 55)
    print("📦 CivicFlow DateSet 전용 VL JSONL 생성")
    print("=" * 55)

    train = convert_split("train")
    valid = convert_split("test")

    for samples, path, tag in [
        (train, OUTPUT_TRAIN, "Train"),
        (valid, OUTPUT_VALID, "Valid"),
    ]:
        with open(path, "w", encoding="utf-8") as f:
            for s in samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        print(f"\n✅ {tag}: {path} ({len(samples):,}개)")

    # 샘플 미리보기
    if train:
        s = train[0]
        print("\n── 샘플 미리보기 ──────────────────────────────")
        for m in s["messages"]:
            c = m["content"]
            if isinstance(c, list):
                types = [p["type"] for p in c]
                print(f"[{m['role']}] types={types}")
            else:
                print(f"[{m['role']}] {str(c)[:80]}")

    print(f"\n🎉 완료! Train={len(train):,}, Valid={len(valid):,}")


if __name__ == "__main__":
    main()
