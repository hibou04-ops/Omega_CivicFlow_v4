import argparse
import json
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Split a Label Studio task JSON array into smaller chunk files."
    )
    parser.add_argument("--input", required=True, help="Source task JSON file.")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where chunk JSON files will be written.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=200,
        help="Number of tasks per chunk.",
    )
    parser.add_argument(
        "--prefix",
        default="labelstudio_tasks_chunk",
        help="Output file prefix.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tasks = json.loads(input_path.read_text(encoding="utf-8"))
    chunk_size = max(1, args.chunk_size)

    total = 0
    for index, start in enumerate(range(0, len(tasks), chunk_size), start=1):
        chunk = tasks[start : start + chunk_size]
        output_path = output_dir / f"{args.prefix}_{index:03d}.json"
        output_path.write_text(
            json.dumps(chunk, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        total += 1
        print(f"{output_path} -> {len(chunk)}")

    print(f"chunks: {total}")
    print(f"tasks: {len(tasks)}")


if __name__ == "__main__":
    main()
