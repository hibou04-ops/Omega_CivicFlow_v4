import os
import base64
import uuid
import datasets
from io import BytesIO
from PIL import Image
from tqdm import tqdm

# [가변 메트릭스 제어 변수 설정]
SOURCE_CACHE_DIR = r"C:\Users\hibou\.cache\huggingface\datasets\didi0di___finance-legal-mrc-chat-template\tableqa_base64\0.0.0\995942e953b825857b759aaa14b140f66daa0a21"

# 렌더링된 이미지가 저장될 물리적 격리 공간
IMAGE_OUTPUT_DIR = r"C:\Users\hibou\Omega_CivicFlow DateSet\tableqa_images"
# 정제로 완료된 새로운 Arrow 데이터셋이 캐싱될 경로
PROCESSED_DATA_DIR = r"C:\Users\hibou\Omega_CivicFlow DateSet\tableqa_processed"

TARGET_RESOLUTION = (448, 448)

def ensure_directory_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

def normalize_and_pad_image(image: Image.Image, target_size: tuple) -> Image.Image:
    if image.mode != 'RGB':
        image = image.convert('RGB')
        
    image.thumbnail(target_size, Image.Resampling.LANCZOS)
    new_image = Image.new("RGB", target_size, (255, 255, 255))
    paste_pos = (
        (target_size[0] - image.size[0]) // 2,
        (target_size[1] - image.size[1]) // 2
    )
    new_image.paste(image, paste_pos)
    return new_image

def process_row(example):
    new_messages = []
    for message in example.get("messages", []):
        role = message.get("role")
        contents = message.get("content", [])
        new_contents = []
        
        if isinstance(contents, list):
            for item in contents:
                if isinstance(item, dict) and item.get("base64"):
                    b64_string = item["base64"]
                    # Remove data URI prefix if it exists
                    if "," in b64_string:
                        b64_string = b64_string.split(",", 1)[1]
                        
                    # Fix incorrect padding by adding missing '='
                    b64_string += "=" * ((4 - len(b64_string) % 4) % 4)
                    
                    try:
                        image_data = base64.b64decode(b64_string)
                        temp_img = Image.open(BytesIO(image_data))
                        final_img = normalize_and_pad_image(temp_img, TARGET_RESOLUTION)
                        
                        unique_filename = f"img_{uuid.uuid4().hex[:12]}.png"
                        save_path = os.path.join(IMAGE_OUTPUT_DIR, unique_filename)
                        final_img.save(save_path, "PNG")
                        
                        new_contents.append({
                            "type": "image",
                            "file_path": save_path,
                            "text": item.get("text", "")
                        })
                    except Exception as e:
                        print(f"Failed to decode or save image: {e}")
                        new_contents.append(item)
                else:
                    new_contents.append(item)
        else:
            new_contents = contents
                
        new_messages.append({
            "role": role,
            "content": new_contents
        })
    example["messages"] = new_messages
    return example

def execute_strategic_preprocessing():
    ensure_directory_exists(IMAGE_OUTPUT_DIR)
    
    datasets.disable_caching()
    
    # Process both tableqa_base64 and tableqa configurations
    configs = ["tableqa_base64", "tableqa"]
    
    for config in configs:
        output_dir = f"{PROCESSED_DATA_DIR}_{config}"
        ensure_directory_exists(output_dir)
        
        print(f"\n[{config}] [1/4] 데이터 적재 (Memory Mapping Initiated)...")
        raw_dataset = datasets.load_dataset("didi0di/finance-legal-mrc-chat-template", config)
        
        print(f"[{config}] [2/4] 엔트로피 소각 및 상전이 프로세스 가동 (Processing...)")
        processed_dataset = raw_dataset.map(
            process_row, 
            num_proc=4, 
            desc=f"{config} 렌더링 및 치환 중"
        )
        
        print(f"[{config}] [3/4] 최적화된 메트릭스 재주조 (Arrow Formatting...)")
        processed_dataset.save_to_disk(output_dir)
        
        print(f"[{config}] [4/4] 작전 완료. 최적화된 데이터셋 격리 경로:\n{output_dir}")

if __name__ == "__main__":
    execute_strategic_preprocessing()
