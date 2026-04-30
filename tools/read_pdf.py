import fitz
doc = fitz.open(r"C:\Users\hibou\Desktop\RAG 방향.pdf")
for i, p in enumerate(doc):
    print(f"=== PAGE {i+1} ===")
    print(p.get_text())
