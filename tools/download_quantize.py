import requests, zipfile, io, os

print("최신 릴리스 확인 중...")
r = requests.get("https://api.github.com/repos/ggerganov/llama.cpp/releases/latest")
data = r.json()
tag = data.get("tag_name", "unknown")
print(f"최신 버전: {tag}")

target_dir = r"C:\llama.cpp\bin"
os.makedirs(target_dir, exist_ok=True)

for asset in data.get("assets", []):
    name = asset["name"]
    if "win" in name.lower() and "x64" in name.lower() and name.endswith(".zip"):
        if "cuda" in name.lower() or "vulkan" in name.lower() or "sycl" in name.lower():
            continue
        size_mb = asset.get("size", 0) // 1024 // 1024
        print(f"다운로드: {name} ({size_mb}MB)")
        dl = requests.get(asset["browser_download_url"], timeout=300)
        z = zipfile.ZipFile(io.BytesIO(dl.content))
        print(f"전체 추출 → {target_dir}")
        z.extractall(target_dir)
        print(f"추출 완료! 파일 수: {len(z.namelist())}")
        # quantize 찾기
        for f in z.namelist():
            if "quantize" in f.lower():
                print(f"  llama-quantize: {os.path.join(target_dir, f)}")
        break
else:
    print("적합한 에셋을 찾지 못함")
