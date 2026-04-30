# ============================================================
# 🚀 CivicFlow Fine-Tuning Script — Qwen2.5-VL-7B (RunPod 버전)
# Model: Qwen/Qwen2.5-VL-7B-Instruct (Vision-Language, QLoRA)
# Data:  civicflow_vl_train.jsonl (이미지 + 텍스트 혼합)
# GPU:   RTX 3090 / 4090 (24GB VRAM, RunPod)
# ============================================================
# 실행 순서:
#   1. pip install -r requirements_qwen_vl.txt --no-cache-dir
#   2. export HF_TOKEN=hf_xxx
#   3. python /workspace/runpod_finetune_qwen_vl.py
# ============================================================

# ── PyTorch 호환성 패치 ──────────────────────────────────────
import torch.nn as nn
if not hasattr(nn.Module, 'set_submodule'):
    def _set_submodule(self, target, module):
        atoms = target.split('.')
        mod = self
        for atom in atoms[:-1]:
            mod = getattr(mod, atom)
        setattr(mod, atoms[-1], module)
    nn.Module.set_submodule = _set_submodule

import os
import json
import torch
import base64
from io import BytesIO
from PIL import Image
from torch.utils.data import Dataset
from transformers import (
    Qwen2_5_VLForConditionalGeneration,
    AutoProcessor,
    BitsAndBytesConfig,
    TrainingArguments,
    Trainer,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

# ── 경로 설정 ────────────────────────────────────────────────
WORKSPACE   = "/workspace"
JSONL_TRAIN = os.path.join(WORKSPACE, "civicflow_train.jsonl")
JSONL_VALID = os.path.join(WORKSPACE, "civicflow_valid.jsonl")
OUTPUT_DIR  = os.path.join(WORKSPACE, "civicflow-qwen-vl-lora")
SAVE_DIR    = os.path.join(WORKSPACE, "models", "civicflow-qwen-vl-lora-final")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SAVE_DIR, exist_ok=True)

# ── HuggingFace 로그인 ───────────────────────────────────────
HF_TOKEN = os.environ.get("HF_TOKEN", None)
if HF_TOKEN:
    from huggingface_hub import login
    login(token=HF_TOKEN)
    print("✅ HuggingFace 로그인 완료")

# ── 모델 설정 ────────────────────────────────────────────────
MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)

print(f"📦 모델 로딩: {MODEL_ID}")
processor = AutoProcessor.from_pretrained(
    MODEL_ID,
    min_pixels=256 * 28 * 28,
    max_pixels=1280 * 28 * 28,   # A100 SXM 80GB → 더 큰 이미지 처리 가능
)

# flash_attention_2 설치 여부 확인
try:
    import flash_attn
    ATTN_IMPL = "flash_attention_2"
    print("✅ flash_attn 사용")
except ImportError:
    ATTN_IMPL = "sdpa"
    print("⚠️ flash_attn 없음, sdpa 사용")

# 분산 학습 호환 device_map (accelerate launch 시 LOCAL_RANK 사용)
local_rank = int(os.environ.get("LOCAL_RANK", 0))
device_map = {"": local_rank}

model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_config,
    device_map=device_map,
    torch_dtype=torch.bfloat16,
    attn_implementation=ATTN_IMPL,
)
model.config.use_cache = False
model = prepare_model_for_kbit_training(model)
print(f"✅ 모델 로딩 완료")

# ── LoRA 설정 ────────────────────────────────────────────────
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()


# ── 데이터셋 클래스 ──────────────────────────────────────────
def data_uri_to_pil(uri: str) -> Image.Image:
    """data:image/...;base64,... → PIL Image"""
    if uri.startswith("data:"):
        header, b64data = uri.split(",", 1)
    else:
        b64data = uri
    img_bytes = base64.b64decode(b64data)
    return Image.open(BytesIO(img_bytes)).convert("RGB")


class VLDataset(Dataset):
    def __init__(self, jsonl_path: str, processor, max_length: int = 1024):
        self.samples = []
        self.processor = processor
        self.max_length = max_length
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.samples.append(json.loads(line))
        print(f"  📂 {os.path.basename(jsonl_path)}: {len(self.samples)}개 로드")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        sample = self.samples[idx]
        messages = sample["messages"]

        # 이미지 추출 + 메시지 변환 (processor 호환 형식)
        images = []
        proc_messages = []

        for msg in messages:
            role    = msg["role"]
            content = msg["content"]

            if isinstance(content, str):
                proc_messages.append({"role": role, "content": content})
                continue

            # list of content parts
            new_parts = []
            for part in content:
                ptype = part.get("type", "")
                if ptype == "image_url":
                    # base64 방식 (느림, 하위호환)
                    uri = part["image_url"]["url"]
                    try:
                        pil_img = data_uri_to_pil(uri)
                        images.append(pil_img)
                        new_parts.append({"type": "image"})
                    except Exception:
                        pass
                elif ptype == "image_file":
                    # 파일 경로 방식 (빠름, preprocess_images.py 이후)
                    img_path = part["image_file"]["path"]
                    try:
                        pil_img = Image.open(img_path).convert("RGB")
                        images.append(pil_img)
                        new_parts.append({"type": "image"})
                    except Exception:
                        pass
                elif ptype == "text":
                    new_parts.append({"type": "text", "text": part.get("text", "")})


            if new_parts:
                proc_messages.append({"role": role, "content": new_parts})

        # chat template 적용
        text = self.processor.apply_chat_template(
            proc_messages,
            tokenize=False,
            add_generation_prompt=False,
        )

        # 인코딩
        if images:
            inputs = self.processor(
                text=[text],
                images=images,
                return_tensors="pt",
                padding=False,
                truncation=False,      # 이미지 토큰 좋리지 않도록 truncation OFF
            )
        else:
            inputs = self.processor(
                text=[text],
                return_tensors="pt",
                padding=False,
                truncation=True,
                max_length=self.max_length,
            )

        input_ids      = inputs["input_ids"].squeeze(0)
        attention_mask = inputs["attention_mask"].squeeze(0)

        # ── Label Masking: assistant 응답 부분만 학습 ──────────────
        # system/user 토큰은 -100으로 마스킹 → loss 계산 제외
        labels = torch.full_like(input_ids, -100)
        tok = self.processor.tokenizer

        # assistant 응답 시작/종료 토큰 찾기
        # Qwen chat template: <|im_start|>assistant\n ... <|im_end|>
        im_start = tok.encode("<|im_start|>", add_special_tokens=False)
        im_end   = tok.encode("<|im_end|>",   add_special_tokens=False)

        ids_list = input_ids.tolist()
        i = 0
        while i < len(ids_list):
            # <|im_start|> 찾기
            if ids_list[i:i+len(im_start)] == im_start:
                j = i + len(im_start)
                # 다음 토큰이 "assistant" 인지 확인
                role_end = j
                while role_end < len(ids_list) and ids_list[role_end] not in im_end:
                    if ids_list[role_end] == tok.encode("\n", add_special_tokens=False)[0]:
                        break
                    role_end += 1
                role_text = tok.decode(ids_list[j:role_end]).strip()
                if role_text == "assistant":
                    # \n 이후부터 <|im_end|> 전까지 레이블 설정
                    content_start = role_end + 1
                    content_end = content_start
                    while content_end < len(ids_list):
                        if ids_list[content_end:content_end+len(im_end)] == im_end:
                            break
                        content_end += 1
                    labels[content_start:content_end] = input_ids[content_start:content_end]
                    i = content_end
                    continue
            i += 1

        result = {
            "input_ids":      input_ids,
            "attention_mask": attention_mask,
            "labels":         labels,
        }
        if "pixel_values" in inputs:
            result["pixel_values"]        = inputs["pixel_values"].squeeze(0)
        if "image_grid_thw" in inputs:
            result["image_grid_thw"]      = inputs["image_grid_thw"].squeeze(0)

        return result


# ── 데이터 콜레이터 ──────────────────────────────────────────
from transformers import DataCollatorWithPadding

def vl_collate_fn(batch):
    """가변 크기 이미지 텐서를 안전하게 배치 처리 (cat 사용)"""
    from torch.nn.utils.rnn import pad_sequence

    pad_id = processor.tokenizer.pad_token_id or 0
    input_ids      = pad_sequence([b["input_ids"] for b in batch],      batch_first=True, padding_value=pad_id)
    attention_mask = pad_sequence([b["attention_mask"] for b in batch], batch_first=True, padding_value=0)
    labels         = pad_sequence([b["labels"] for b in batch],         batch_first=True, padding_value=-100)

    result = {
        "input_ids":      input_ids,
        "attention_mask": attention_mask,
        "labels":         labels,
    }

    # pixel_values: 이미지마다 패치 수가 다름 → cat으로 이어붙이기
    pixel_vals = [b["pixel_values"] for b in batch if "pixel_values" in b]
    if pixel_vals:
        result["pixel_values"] = torch.cat(pixel_vals, dim=0)

    # image_grid_thw: [num_images, 3] → cat
    grid_vals = [b["image_grid_thw"] for b in batch if "image_grid_thw" in b]
    if grid_vals:
        result["image_grid_thw"] = torch.cat(
            [g.unsqueeze(0) if g.dim() == 1 else g for g in grid_vals], dim=0
        )

    return result


# ── 데이터셋 로드 ────────────────────────────────────────────
print("\n📂 데이터셋 로딩...")
MAX_SEQ_LEN = 4096  # A100 80GB → 충분한 VRAM, 이미지 토큰 충분히 포함

train_dataset = VLDataset(JSONL_TRAIN, processor, max_length=MAX_SEQ_LEN)
valid_dataset = VLDataset(JSONL_VALID, processor, max_length=MAX_SEQ_LEN)

# ── 학습 설정 ────────────────────────────────────────────────
training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,

    # A100 SXM 80GB — VL 가변 이미지로 batch_size=1 안전
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,      # 실효 배치 = 8
    gradient_checkpointing=True,

    # 학습률
    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    warmup_steps=20,

    # 에폭
    num_train_epochs=1,
    max_steps=3000,             # 최대 3000 steps (~3.7시간, $9)
    save_strategy="steps",
    save_steps=500,             # 500 steps마다 체크포인트 (평가X)
    save_total_limit=3,

    # 평가 — 검증셋 13K개 평가가 35분 소요 → 마지막에만 1회
    eval_strategy="no",         # ← 50마다 35분 낭비 제거
    # eval_steps=1000,          # 필요시 활성화

    # A100 SXM은 BF16 네이티브 지원 → 속도 최대화
    bf16=True,
    fp16=False,
    optim="paged_adamw_8bit",
    tf32=True,                          # A100 전용 TF32 가속

    # 로깅
    logging_steps=5,
    report_to="none",
    dataloader_pin_memory=False,
    dataloader_num_workers=0,           # 멀티프로세스 오류 방지
    remove_unused_columns=False,
)

# ── 학습 시작 ────────────────────────────────────────────────
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=valid_dataset,
    data_collator=vl_collate_fn,
)

print("\n🚀 Qwen2.5-VL-7B 학습 시작!")
trainer.train(resume_from_checkpoint="/workspace/civicflow-qwen-vl-lora/checkpoint-2500")
print("✅ 학습 완료!")

# ── 저장 ────────────────────────────────────────────────────
trainer.save_model(SAVE_DIR)
processor.save_pretrained(SAVE_DIR)
print(f"✅ 모델 저장: {SAVE_DIR}")

print("""
╔══════════════════════════════════════════════════════╗
║  🎉 Qwen2.5-VL-7B 파인튜닝 완료! (RunPod)            ║
║                                                      ║
║  저장 위치: /workspace/models/civicflow-qwen-vl-lora  ║
║                                                      ║
║  다음: python /workspace/test_inference_vl.py        ║
╚══════════════════════════════════════════════════════╝
""")
