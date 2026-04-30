import torch

print("CUDA available:", torch.cuda.is_available())
print("현재 device:", next(model.parameters()).device)

if str(next(model.parameters()).device) == "cpu":
    model = model.to("cuda")
    print("→ CUDA 이동 완료")

print("최종 device:", next(model.parameters()).device)

_ = model.encode(["워밍업"], batch_size=1, normalize_embeddings=True)
print("워밍업 완료")
