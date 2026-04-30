#!/bin/bash
# ============================================================
# EXAONE-3.5 QLoRA 학습 환경 셋업 — GCE L4 GPU
# Omega CivicFlow
#
# 실행: bash setup_gce_training.sh
# ============================================================

set -e

echo "══════════════════════════════════════════════"
echo "🔧 EXAONE QLoRA 학습 환경 셋업 시작"
echo "══════════════════════════════════════════════"

# ── 1. GPU 확인 ──
echo ""
echo "📌 Step 1: GPU 확인"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo ""

# ── 2. Python 환경 ──
echo "📌 Step 2: Python 환경 확인"
python3 --version
pip3 --version
echo ""

# ── 3. 핵심 패키지 설치 ──
echo "📌 Step 3: 핵심 패키지 설치"
pip3 install --upgrade pip

pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

pip3 install \
    transformers==4.46.0 \
    peft==0.13.2 \
    bitsandbytes==0.44.1 \
    accelerate==1.1.1 \
    datasets \
    scipy \
    sentencepiece \
    protobuf \
    huggingface_hub

# Flash Attention (선택사항 — L4에서 성능 향상)
echo ""
echo "📌 Step 3b: Flash Attention 설치 시도 (실패해도 학습 가능)"
pip3 install flash-attn --no-build-isolation 2>/dev/null || \
    echo "⚠️  flash-attn 설치 실패 — sdpa fallback 사용 (정상 동작)"

echo ""
echo "✅ 패키지 설치 완료"
echo ""

# ── 4. CUDA 확인 ──
echo "📌 Step 4: CUDA / PyTorch 확인"
python3 -c "
import torch
print(f'  PyTorch version : {torch.__version__}')
print(f'  CUDA available  : {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'  GPU name        : {torch.cuda.get_device_name(0)}')
    print(f'  GPU memory      : {torch.cuda.get_device_properties(0).total_mem / 1e9:.1f} GB')
    print(f'  BF16 support    : {torch.cuda.is_bf16_supported()}')
import transformers, peft, bitsandbytes
print(f'  transformers    : {transformers.__version__}')
print(f'  peft            : {peft.__version__}')
print(f'  bitsandbytes    : {bitsandbytes.__version__}')
"
echo ""

# ── 5. 작업 디렉토리 ──
echo "📌 Step 5: 작업 디렉토리 준비"
WORKDIR="$HOME/exaone-training"
mkdir -p "$WORKDIR"
echo "  작업 디렉토리: $WORKDIR"
echo ""

# ── 6. 안내 메시지 ──
echo "══════════════════════════════════════════════"
echo "✅ 환경 셋업 완료!"
echo "══════════════════════════════════════════════"
echo ""
echo "📋 다음 단계:"
echo ""
echo "  1. HuggingFace 토큰 설정 (EXAONE 게이트 모델 접근용):"
echo "     export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxx"
echo ""
echo "  2. 로컬에서 파일 업로드 (별도 터미널에서):"
echo "     gcloud compute scp \\"
echo "       tools/exaone_qlora_gce.py \\"
echo "       datasets/dart_train.jsonl \\"
echo "       datasets/dart_valid.jsonl \\"
echo "       INSTANCE_NAME:~/exaone-training/ \\"
echo "       --zone=us-central1-a"
echo ""
echo "  3. Dry-run (데이터 검증):"
echo "     cd ~/exaone-training"
echo "     python3 exaone_qlora_gce.py --dry-run"
echo ""
echo "  4. 학습 시작:"
echo "     HF_TOKEN=hf_xxx python3 exaone_qlora_gce.py"
echo ""
echo "  5. 학습 완료 후 어댑터 다운로드 (로컬에서):"
echo "     gcloud compute scp --recurse \\"
echo "       INSTANCE_NAME:~/exaone-dart-adapter ./ \\"
echo "       --zone=us-central1-a"
echo ""
echo "══════════════════════════════════════════════"
