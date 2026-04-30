import time, re

def split_chunks(text, size=12000):
    paras = re.split(r'\n\s*\n', text)
    chunks, cur, clen = [], [], 0
    for p in paras:
        p = p.strip()
        if not p: continue
        pl = len(p)
        if pl > size:
            if cur:
                chunks.append("\n\n".join(cur))
                cur, clen = [], 0
            for s in range(0, pl, size):
                chunks.append(p[s:s + size])
            continue
        if clen + pl + 2 > size and cur:
            chunks.append("\n\n".join(cur))
            cur, clen = [], 0
        cur.append(p)
        clen += pl + 2
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks

# 랜덤한 더미 텍스트 500만 자 생성 (약 10만 개의 문단)
dummy_para = "이것은 테스트를 위한 더미 텍스트입니다. " * 3 + "\n\n"
text = dummy_para * 30000
print(f"생성된 텍스트 길이: {len(text):,}자")

t0 = time.time()
chunks = split_chunks(text)
t1 = time.time()

print(f"청크 개수: {len(chunks)}개")
print(f"파이썬 CPU 청킹(분할) 소요 시간: {t1 - t0:.5f}초")
