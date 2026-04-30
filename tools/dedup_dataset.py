import os
import hashlib
import zipfile
import shutil
import time

src_dir = r"C:\Users\hibou\Desktop\DataSet"
dst_dir = r"C:\Users\hibou\Desktop\DataSet_Cleaned"
zip_path = r"C:\Users\hibou\Desktop\DataSet_Colab.zip"

def get_hash(filepath):
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            buf = f.read(65536 * 16)
            while len(buf) > 0:
                hasher.update(buf)
                buf = f.read(65536 * 16)
        return hasher.hexdigest()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

def main():
    print("Starting deduplication process...")
    if not os.path.exists(dst_dir):
        os.makedirs(dst_dir)

    seen_hashes = set()
    duplicates = 0
    added = 0
    start_time = time.time()

    if not os.path.exists(src_dir):
        print(f"Source directory not found: {src_dir}")
        return

    files = os.listdir(src_dir)
    # Sort files by length, so standard names like .zip come before .zip.pdf
    files.sort(key=lambda x: (len(x), x))
    total_files = len(files)
    print(f"Found {total_files} files in the dataset.")
    print("Hashing, copying unique files, and creating ZIP archive for Colab...")

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, filename in enumerate(files):
            filepath = os.path.join(src_dir, filename)
            if os.path.isfile(filepath):
                h = get_hash(filepath)
                if h is not None:
                    if h not in seen_hashes:
                        seen_hashes.add(h)
                        # Copy to cleaned dir
                        shutil.copy2(filepath, os.path.join(dst_dir, filename))
                        # Add to ZIP
                        zf.write(filepath, arcname=filename)
                        added += 1
                    else:
                        duplicates += 1
            
            if (i + 1) % 500 == 0:
                print(f"Processed {i + 1}/{total_files} files...")

    end_time = time.time()
    print("\n--- Deduplication Complete ---")
    print(f"Time taken: {end_time - start_time:.2f} seconds")
    print(f"Unique files kept: {added}")
    print(f"Duplicate files ignored: {duplicates}")
    print(f"Cleaned folder created at: {dst_dir}")
    print(f"Colab Upload Ready ZIP created at: {zip_path}")
    print("You can easily upload DataSet_Colab.zip to Google Colab and unzip it there.")

if __name__ == '__main__':
    main()
