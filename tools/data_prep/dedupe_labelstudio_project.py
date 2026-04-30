import argparse
import json
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


DEFAULT_DB_PATH = Path(
    r"C:\Users\hibou\AppData\Local\label-studio\label-studio\label_studio.sqlite3"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Deduplicate Label Studio tasks inside one project by doc_id + section_file."
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to Label Studio sqlite database.",
    )
    parser.add_argument(
        "--project-id",
        type=int,
        required=True,
        help="Target Label Studio project id.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete duplicate tasks. Without this flag, only print a dry-run summary.",
    )
    parser.add_argument(
        "--backup-path",
        help="Optional sqlite backup path. Defaults to a timestamped .bak next to the DB.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=10,
        help="How many duplicate groups to preview.",
    )
    return parser.parse_args()


def load_tasks(conn: sqlite3.Connection, project_id: int):
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    completion_counts = {
        row["task_id"]: row["cnt"]
        for row in cur.execute(
            "SELECT task_id, COUNT(*) AS cnt FROM task_completion WHERE project_id=? GROUP BY task_id",
            (project_id,),
        )
    }
    draft_counts = {
        row["task_id"]: row["cnt"]
        for row in cur.execute(
            """
            SELECT d.task_id, COUNT(*) AS cnt
            FROM tasks_annotationdraft d
            JOIN task t ON t.id = d.task_id
            WHERE t.project_id=?
            GROUP BY d.task_id
            """,
            (project_id,),
        )
    }

    tasks = []
    for row in cur.execute(
        "SELECT id, is_labeled, total_annotations, data FROM task WHERE project_id=? ORDER BY id",
        (project_id,),
    ):
        data = json.loads(row["data"])
        key = (str(data.get("doc_id") or ""), str(data.get("section_file") or ""))
        tasks.append(
            {
                "id": row["id"],
                "is_labeled": int(bool(row["is_labeled"])),
                "total_annotations": int(row["total_annotations"] or 0),
                "completion_count": int(completion_counts.get(row["id"], 0)),
                "draft_count": int(draft_counts.get(row["id"], 0)),
                "key": key,
                "data": data,
            }
        )
    return tasks


def choose_keeper(items: list[dict]) -> dict:
    return sorted(
        items,
        key=lambda item: (
            -item["completion_count"],
            -item["draft_count"],
            -item["total_annotations"],
            -item["is_labeled"],
            item["id"],
        ),
    )[0]


def delete_in_chunks(cur: sqlite3.Cursor, sql: str, ids: list[int], chunk_size: int = 400):
    if not ids:
        return
    for start in range(0, len(ids), chunk_size):
        chunk = ids[start : start + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        cur.execute(sql.format(placeholders=placeholders), chunk)


def summarize(tasks: list[dict], sample_limit: int):
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for task in tasks:
        by_key[task["key"]].append(task)

    duplicate_groups = []
    delete_ids: list[int] = []

    for key, items in by_key.items():
        if len(items) <= 1:
            continue
        keeper = choose_keeper(items)
        duplicates = [item for item in items if item["id"] != keeper["id"]]
        delete_ids.extend(item["id"] for item in duplicates)
        duplicate_groups.append((key, keeper, duplicates))

    duplicate_groups.sort(key=lambda entry: (-len(entry[2]), entry[0]))

    print(f"tasks_total: {len(tasks)}")
    print(f"unique_keys: {len(by_key)}")
    print(f"duplicate_groups: {len(duplicate_groups)}")
    print(f"tasks_to_delete: {len(delete_ids)}")
    print()
    print("sample_groups:")
    for key, keeper, duplicates in duplicate_groups[:sample_limit]:
        print(
            {
                "key": key,
                "keep": {
                    "task_id": keeper["id"],
                    "is_labeled": keeper["is_labeled"],
                    "completion_count": keeper["completion_count"],
                    "draft_count": keeper["draft_count"],
                },
                "delete": [
                    {
                        "task_id": item["id"],
                        "is_labeled": item["is_labeled"],
                        "completion_count": item["completion_count"],
                        "draft_count": item["draft_count"],
                    }
                    for item in duplicates
                ],
            }
        )

    return duplicate_groups, delete_ids


def backup_db(db_path: Path, backup_path: Path | None):
    if backup_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.with_suffix(db_path.suffix + f".{stamp}.bak")
    shutil.copy2(db_path, backup_path)
    print(f"backup_created: {backup_path}")
    return backup_path


def apply_delete(db_path: Path, project_id: int, delete_ids: list[int], backup_path: Path | None):
    if not delete_ids:
        print("nothing_to_delete")
        return

    backup_db(db_path, backup_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        delete_in_chunks(cur, "DELETE FROM tasks_annotationdraft WHERE task_id IN ({placeholders})", delete_ids)
        delete_in_chunks(cur, "DELETE FROM tasks_tasklock WHERE task_id IN ({placeholders})", delete_ids)
        delete_in_chunks(cur, "DELETE FROM fsm_taskstate WHERE task_id IN ({placeholders})", delete_ids)
        delete_in_chunks(cur, "DELETE FROM task_comment_authors WHERE task_id IN ({placeholders})", delete_ids)
        delete_in_chunks(cur, "DELETE FROM task_completion WHERE task_id IN ({placeholders})", delete_ids)
        delete_in_chunks(cur, "DELETE FROM prediction WHERE task_id IN ({placeholders})", delete_ids)
        delete_in_chunks(cur, "DELETE FROM task WHERE id IN ({placeholders})", delete_ids)
        cur.execute("UPDATE project SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
        conn.commit()
        print(f"deleted_tasks: {len(delete_ids)}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    args = parse_args()
    db_path = Path(args.db)
    backup_path = Path(args.backup_path) if args.backup_path else None

    conn = sqlite3.connect(db_path)
    try:
        tasks = load_tasks(conn, args.project_id)
    finally:
        conn.close()

    duplicate_groups, delete_ids = summarize(tasks, args.sample_limit)

    if args.apply:
        apply_delete(db_path, args.project_id, delete_ids, backup_path)
        print("done: apply")
    else:
        print("done: dry-run")


if __name__ == "__main__":
    main()
