from sentence_transformers import CrossEncoder
import torch

device = "cuda" if torch.cuda.is_available() else "cpu"

model = CrossEncoder(
    "dragonkue/bge-reranker-v2-m3-ko",
    default_activation_function=torch.nn.Sigmoid(),
    device=device,
)