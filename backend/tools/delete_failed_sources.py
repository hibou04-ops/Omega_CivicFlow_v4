import json
import os
import pathlib

FAILED_FILE = pathlib.Path(r"C:\Users\hibou\Omega_CivicFlow_v4\backend\tools\reindex_v2_failed.json")

def delete_failed_sources():
    if not FAILED_FILE.exists():
        print("Failed log not found.")
        return

    with open(FAILED_FILE, "r", encoding="utf-8") as f:
        failed_data = json.load(f)

    deleted_count = 0
    not_found_count = 0

    for item in failed_data:
        source_path = item.get("source_path")
        if source_path and os.path.exists(source_path):
            try:
                os.remove(source_path)
                print(f"Deleted: {source_path}")
                deleted_count += 1
            except Exception as e:
                print(f"Error deleting {source_path}: {e}")
        else:
            print(f"File not found (already deleted?): {source_path}")
            not_found_count += 1

    print("-" * 40)
    print(f"Total processed: {len(failed_data)}")
    print(f"Successfully deleted: {deleted_count}")
    print(f"Not found: {not_found_count}")

if __name__ == "__main__":
    delete_failed_sources()
