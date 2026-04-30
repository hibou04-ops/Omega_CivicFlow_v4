#!/bin/bash
# ============================================================
# EXAONE-3.5 QLoRA 학습 환경 — RunPod (H100/A100/A40)
#
# 실행: bash setup_runpod_training.sh
# ============================================================

set -e

echo "══════════════════════════════════════════════"
echo "🔧 EXAONE QLoRA 학습 환경 셋업 (RunPod)"
echo "══════════════════════════════════════════════"

# ── 1. GPU 확인 ──
echo ""
echo "📌 Step 1: GPU 확인"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo ""

# ── 2. Python 환경 확인 ──
echo "📌 Step 2: Python 환경"
python3 --version
pip3 --version
echo ""

# ── 3. 핵심 패키지 설치 ──
echo "📌 Step 3: 핵심 패키지 설치"
pip3 install --upgrade pip

# RunPod PyTorch 2.4.0 템플릿에는 이미 PyTorch + CUDA 설치됨
# 추가 패키지만 설치
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

# Flash Attention (H100/A100에서 성능 향상)
echo ""
echo "📌 Step 3b: Flash Attention 설치"
pip3 install flash-attn --no-build-isolation 2>/dev/null || \
    echo "⚠️  flash-attn 설치 실패 — sdpa fallback 사용 (정상 동작)"

echo ""
echo "✅ 패키지 설치 완료"
echo ""

# ── 4. CUDA + PyTorch 검증 ──
echo "📌 Step 4: CUDA / PyTorch 검증"
python3 -c "
import torch
print(f'  PyTorch   : {torch.__version__}')
print(f'  CUDA      : {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'  GPU       : {torch.cuda.get_device_name(0)}')
    print(f'  VRAM      : {torch.cuda.get_device_properties(0).total_mem / 1e9:.1f} GB')
    print(f'  BF16      : {torch.cuda.is_bf16_supported()}')
import transformers, peft, bitsandbytes
print(f'  transformers : {transformers.__version__}')
print(f'  peft         : {peft.__version__}')
print(f'  bitsandbytes : {bitsandbytes.__version__}')
"
echo ""

# ── 5. 작업 디렉토리 ──
echo "📌 Step 5: 작업 디렉토리"
WORKDIR="/workspace/exaone-training"
mkdir -p "$WORKDIR"
echo "  디렉토리: $WORKDIR"

# ── 완료 ──
echo ""
echo "══════════════════════════════════════════════"
echo "✅ 환경 셋업 완료!"
echo "══════════════════════════════════════════════"
echo ""
echo "📋 다음 단계:"
echo ""
echo "  1. HuggingFace 토큰 설정:"
echo "     export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxx"
echo ""
echo "  2. 데이터 업로드 (Jupyter에서 업로드 또는 wget):"
echo "     cd /workspace/exaone-training"
echo "     # Jupyter 파일 업로드 기능 사용"
echo ""
echo "  3. Dry-run (데이터 검증):"
echo "     python3 exaone_qlora_runpod.py --dry-run"
echo ""
echo "  4. 학습 시작:"
echo "     HF_TOKEN=hf_xxx python3 exaone_qlora_runpod.py"
echo ""
echo "  5. 학습 완료 후 어댑터 다운로드:"
echo "     # Jupyter에서 exaone-dart-adapter 폴더를 zip 다운로드"
echo "     cd /workspace && zip -r adapter.zip exaone-dart-adapter"
echo ""
echo "══════════════════════════════════════════════"
