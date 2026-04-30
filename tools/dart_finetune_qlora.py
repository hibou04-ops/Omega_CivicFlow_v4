# ============================================================
# 🚀 DART 텍스트 전용 QLoRA 파인튜닝 스크립트
# Model  : Qwen/Qwen2.5-7B-Instruct
# Data   : dart_train.jsonl / dart_valid.jsonl
# Format : {"messages": [{"role": "system/user/assistant", "content": "..."}]}
# GPU    : RunPod A100 SXM 80GB
#
# 실행 예시:
#   RunPod  : HF_TOKEN=hf_xxx python /workspace/dart_finetune_qlora.py
#   DryRun  : python dart_finetune_qlora.py --dry-run   (모델 로딩 없이 데이터만 확인)
#
# 설치:
#   pip install transformers peft bitsandbytes accelerate trl flash-attn
# ============================================================

import os, json, argparse, glob, torch
from torch.utils.data import Dataset
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

# ── 인자 파싱 ────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--model-id", type=str,
                    default="Qwen/Qwen2.5-7B-Instruct",
                    help="HuggingFace 모델 ID")
parser.add_argument("--train",    type=str, default=None,
                    help="dart_train.jsonl 경로 (미지정 시 자동 탐색)")
parser.add_argument("--valid",    type=str, default=None,
                    help="dart_valid.jsonl 경로 (미지정 시 자동 탐색)")
parser.add_argument("--output",   type=str, default=None,
                    help="LoRA 체크포인트 출력 디렉토리")
parser.add_argument("--dry-run",  action="store_true",
                    help="모델 로딩 없이 데이터 1개만 로드해서 구조 확인 후 종료")
args = parser.parse_args()

# ── 경로 자동 탐색 ────────────────────────────────────────────
WORKSPACE = "/workspace" if os.path.isdir("/workspace") else "."

def find_file(name, hint=None):
    """지정 경로 → workspace → 현재 디렉토리 순으로 탐색 (중복 제거)"""
    if hint and os.path.exists(hint):
        return os.path.abspath(hint)
    seen = set()
    candidates = []
    for p in glob.glob(f"{WORKSPACE}/**/{name}", recursive=True) + \
              glob.glob(f"./**/{name}",           recursive=True):
        abs_p = os.path.abspath(p)
        if abs_p not in seen:
            seen.add(abs_p)
            candidates.append(abs_p)
    if candidates:
        return candidates[0]
    raise FileNotFoundError(
        f"'{name}' 파일을 찾을 수 없습니다. --train / --valid 로 직접 지정하세요."
    )

JSONL_TRAIN = find_file("dart_train.jsonl", args.train)
JSONL_VALID = find_file("dart_valid.jsonl", args.valid)
OUTPUT_DIR  = args.output or os.path.join(WORKSPACE, "dart-qwen-lora")
SAVE_DIR    = os.path.join(WORKSPACE, "models", "dart-qwen-lora-final")

print(f"📂 Train : {JSONL_TRAIN}")
print(f"📂 Valid : {JSONL_VALID}")
print(f"📂 Output: {OUTPUT_DIR}")

# ── GPU 자동 감지 (A100 / H100) ──────────────────────────────
import subprocess as _sp
_gpu_name = ""
try:
    _gpu_name = _sp.check_output(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        text=True
    ).strip().upper()
except Exception:
    pass

IS_H100 = "H100" in _gpu_name

ENV = {
    # H100: batch=4, seq=4096
    # A100: batch=2, seq=4096
    "batch_size":    4 if IS_H100 else 2,
    "grad_accum":    4 if IS_H100 else 8,    # 실효 배치 = 16 공통 유지
    "max_seq_len":   4096,                   # ★ 4096 — DART 문서 절단 방지
    "max_steps":     2000,
    "save_steps":    500,
    "num_workers":   4,
    "desc":          f"RunPod {'H100' if IS_H100 else 'A100'} SXM 80GB (자동 감지)",
}
COMPUTE_DTYPE = torch.bfloat16   # A100/H100 모두 BF16 네이티브


print(f"\n⚙️  실행 환경  : {ENV['desc']}")
print(f"   실효 배치  : {ENV['batch_size']} × {ENV['grad_accum']} = "
      f"{ENV['batch_size'] * ENV['grad_accum']}")

# flash_attention_2 자동 감지 (A100 최적)
try:
    import flash_attn
    ATTN_IMPL = "flash_attention_2"
    print("✅ flash_attention_2 사용")
except ImportError:
    ATTN_IMPL = "sdpa"
    print("⚠️  flash_attn 없음 → sdpa 사용 (pip install flash-attn 권장)")

# ── [FIX #1] dry-run: 모델 로딩 전 데이터만 검증하고 즉시 종료 ──
# (원본: 모델 로딩까지 완료 후 dry-run 분기 → GB 단위 다운로드 낭비)
if args.dry_run:
    print("\n🔍 [DRY-RUN] 모델 로딩 없이 데이터 구조만 확인합니다.")
    _tok = AutoTokenizer.from_pretrained(args.model_id, use_fast=True)
    _tok.pad_token    = _tok.eos_token
    _tok.padding_side = "right"

    with open(JSONL_TRAIN, "r", encoding="utf-8") as _f:
        _sample = json.loads(_f.readline().strip())

    messages     = _sample["messages"]
    full_text    = _tok.apply_chat_template(messages, tokenize=False,
                                            add_generation_prompt=False)
    no_asst      = [m for m in messages if m["role"] != "assistant"]
    prefix_text  = _tok.apply_chat_template(no_asst, tokenize=False,
                                            add_generation_prompt=True)
    full_ids     = _tok(full_text,   return_tensors="pt")["input_ids"].squeeze()
    prefix_ids   = _tok(prefix_text, return_tensors="pt")["input_ids"].squeeze()

    # 경계 클램핑 검증
    prefix_len   = min(len(prefix_ids), len(full_ids))
    labels       = full_ids.clone()
    labels[:prefix_len] = -100
    learn_tokens = (labels != -100).sum().item()

    print(f"  전체 토큰 수     : {len(full_ids)}")
    print(f"  prefix 토큰 수   : {len(prefix_ids)}")
    print(f"  학습 대상 토큰   : {learn_tokens}")
    print(f"  학습 대상 텍스트 : {_tok.decode(full_ids[prefix_len:prefix_len+80])!r}")

    if learn_tokens == 0:
        print("❌ 경고: 학습 가능한 토큰이 0개입니다. JSONL 포맷을 확인하세요.")
    else:
        print("\n✅ Dry-run 완료 — 구조 정상.")
    exit(0)

# ── 디렉토리 생성 (dry-run 이후에만) ────────────────────────
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SAVE_DIR,   exist_ok=True)

# ── HuggingFace 로그인 ────────────────────────────────────────
HF_TOKEN = os.environ.get("HF_TOKEN")
if HF_TOKEN:
    from huggingface_hub import login
    login(token=HF_TOKEN)
    print("✅ HuggingFace 로그인 완료")

# ── 4-bit NF4 양자화 설정 ─────────────────────────────────────
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=COMPUTE_DTYPE,
    bnb_4bit_use_double_quant=True,
)

MODEL_ID = args.model_id
print(f"\n📦 모델 로딩: {MODEL_ID}")

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=True)
tokenizer.pad_token    = tokenizer.eos_token
tokenizer.padding_side = "right"

model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_config,
    device_map="auto",
    attn_implementation=ATTN_IMPL,   # A100: flash_attention_2
)
model.config.use_cache = False
model = prepare_model_for_kbit_training(
    model,
    use_gradient_checkpointing=True,   # 명시적 지정
)
print("✅ 베이스 모델 로딩 완료")

# ── LoRA 설정 ─────────────────────────────────────────────────
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


# ── 데이터셋 클래스 ───────────────────────────────────────────
class DartDataset(Dataset):
    def __init__(self, jsonl_path: str, tokenizer, max_length: int = 2048):
        self.tokenizer  = tokenizer
        self.max_length = max_length
        self.samples    = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.samples.append(json.loads(line))
        print(f"  📂 {os.path.basename(jsonl_path)}: {len(self.samples)}개 로드")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        messages = self.samples[idx]["messages"]

        # 전체 대화 → chat template 적용
        full_text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False
        )
        # system/user prefix (assistant 시작 토큰까지)
        no_asst      = [m for m in messages if m["role"] != "assistant"]
        prefix_text  = self.tokenizer.apply_chat_template(
            no_asst, tokenize=False, add_generation_prompt=True
        )

        full_ids   = self.tokenizer(
            full_text, truncation=True, max_length=self.max_length,
            return_tensors="pt"
        )["input_ids"].squeeze(0)

        prefix_ids = self.tokenizer(
            prefix_text, truncation=True, max_length=self.max_length,
            return_tensors="pt"
        )["input_ids"].squeeze(0)

        attention_mask = torch.ones_like(full_ids)

        # prefix_len을 full_ids 길이로 클램핑 → truncation 시 loss=0 방지
        prefix_len = min(len(prefix_ids), len(full_ids))

        labels = full_ids.clone()
        labels[:prefix_len] = -100  # prefix는 loss 계산 제외

        # ★ 학습 가능한 토큰이 0개면 다음 샘플로 — loss=0.0 방지
        learn_tokens = (labels != -100).sum().item()
        if learn_tokens == 0:
            next_idx = (idx + 1) % len(self.samples)
            return self.__getitem__(next_idx)

        return {
            "input_ids":      full_ids,
            "attention_mask": attention_mask,
            "labels":         labels,
        }

    def count_valid_samples(self):
        """학습 가능한 샘플 수 사전 집계 (디버깅용)"""
        valid = 0
        for i in range(min(len(self.samples), 100)):  # 처음 100개만 샘플링
            item = self[i]
            if (item["labels"] != -100).sum().item() > 0:
                valid += 1
        ratio = valid / min(len(self.samples), 100) * 100
        print(f"  ✅ 유효 샘플 비율 (샘플링): {valid}/100 ({ratio:.1f}%)")
        if ratio < 50:
            print("  ⚠️  유효 샘플이 50% 미만 — max_seq_len을 더 늘리거나 데이터를 확인하세요.")


# ── 데이터셋 로드 ─────────────────────────────────────────────
print("\n📂 데이터셋 로딩...")
train_dataset = DartDataset(JSONL_TRAIN, tokenizer, max_length=ENV["max_seq_len"])
valid_dataset = DartDataset(JSONL_VALID, tokenizer, max_length=ENV["max_seq_len"])

# ★ 유효 샘플 비율 사전 확인 — 낮으면 조기 경고
train_dataset.count_valid_samples()

# ── 자동 체크포인트 감지 ──────────────────────────────────────
def find_latest_checkpoint(output_dir):
    checkpoints = sorted(
        glob.glob(os.path.join(output_dir, "checkpoint-*")),
        key=lambda x: int(x.split("-")[-1])
    )
    return checkpoints[-1] if checkpoints else None

latest_ckpt = find_latest_checkpoint(OUTPUT_DIR)
if latest_ckpt:
    print(f"\n♻️  체크포인트 감지: {latest_ckpt} → 이어서 학습")

# ── 학습 설정 ─────────────────────────────────────────────────
training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,

    per_device_train_batch_size=ENV["batch_size"],
    gradient_accumulation_steps=ENV["grad_accum"],
    gradient_checkpointing=True,

    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    warmup_steps=20,

    max_steps=ENV["max_steps"],
    save_strategy="steps",
    save_steps=ENV["save_steps"],
    save_total_limit=3,

    eval_strategy="steps",
    eval_steps=ENV["save_steps"],

    bf16=True,           # A100 네이티브 BF16
    fp16=False,
    tf32=True,           # A100 전용 TF32 가속
    optim="paged_adamw_8bit",

    logging_steps=10,
    report_to="none",
    dataloader_num_workers=ENV["num_workers"],
    remove_unused_columns=False,
    label_names=["labels"],
)

# ── DataCollator ──────────────────────────────────────────────
data_collator = DataCollatorForSeq2Seq(
    tokenizer=tokenizer,
    model=None,
    padding=True,
    pad_to_multiple_of=8,
    label_pad_token_id=-100,
)

# ── 학습 시작 ─────────────────────────────────────────────────
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=valid_dataset,
    data_collator=data_collator,
)

print(f"\n🚀 QLoRA 학습 시작! (환경: {ENV['desc']})")
trainer.train(resume_from_checkpoint=latest_ckpt)   # None이면 처음부터
print("✅ 학습 완료!")

# ── LoRA 어댑터 저장 ──────────────────────────────────────────
trainer.save_model(SAVE_DIR)
tokenizer.save_pretrained(SAVE_DIR)
print(f"✅ LoRA 어댑터 저장: {SAVE_DIR}")

print("""
╔══════════════════════════════════════════════════════════╗
║  🎉 DART QLoRA 파인튜닝 완료!                             ║
║                                                          ║
║  LoRA 어댑터: /workspace/models/dart-qwen-lora-final     ║
║                                                          ║
║  다음 단계:                                               ║
║    HuggingFace Hub 업로드:                               ║
║      trainer.push_to_hub("your-repo/dart-qwen-lora")    ║
║    추론 테스트:                                            ║
║      python dart_inference_test.py                      ║
╚══════════════════════════════════════════════════════════╝
""")
