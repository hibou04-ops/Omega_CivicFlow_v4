"""
RunPod에서 실행: JSONL의 base64 이미지를 PNG 파일로 추출
실행: python /workspace/preprocess_images.py
결과: /workspace/images/{split}/{idx}.png + 새 JSONL (파일 경로 참조)
"""
import json, os, base64, sys
from pathlib import Path

WORKSPACE = "/workspace"
SPLITS = [
    (f"{WORKSPACE}/civicflow_only_train.jsonl", f"{WORKSPACE}/civicflow_only_train_fast.jsonl", "train"),
    (f"{WORKSPACE}/civicflow_only_valid.jsonl", f"{WORKSPACE}/civicflow_only_valid_fast.jsonl", "valid"),
]

for in_path, out_path, split in SPLITS:
    img_dir = Path(f"{WORKSPACE}/images/{split}")
    img_dir.mkdir(parents=True, exist_ok=True)

    with open(in_path, encoding="utf-8") as fin, \
         open(out_path, "w", encoding="utf-8") as fout:

        for idx, line in enumerate(fin):
            sample = json.loads(line)
            new_messages = []

            for msg in sample["messages"]:
                content = msg["content"]
                if not isinstance(content, list):
                    new_messages.append(msg)
                    continue

                new_parts = []
                img_count = 0
                for part in content:
                    if part.get("type") == "image_url":
                        url = part["image_url"]["url"]
                        if url.startswith("data:"):
                            _, b64 = url.split(",", 1)
                        else:
                            b64 = url

                        img_path = img_dir / f"{idx}_{img_count}.png"
                        with open(img_path, "wb") as f:
                            f.write(base64.b64decode(b64))

                        new_parts.append({
                            "type": "image_file",
                            "image_file": {"path": str(img_path)}
                        })
                        img_count += 1
                    else:
                        new_parts.append(part)

                new_messages.append({"role": msg["role"], "content": new_parts})

            fout.write(json.dumps({"messages": new_messages}, ensure_ascii=False) + "\n")

            if idx % 100 == 0:
                print(f"  [{split}] {idx}개 처리...", flush=True)

    print(f"✅ {split} 완료: {out_path}")

print("🎉 전처리 완료! 이제 fast JSONL로 학습 시작 가능")
