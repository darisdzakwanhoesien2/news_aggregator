# =====================================================
# FIX PYTHON PATH (MUST BE FIRST)
# =====================================================
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# =====================================================
# IMPORTS
# =====================================================
import json
from utils.x_text_metrics import extract_metrics_from_text

DATA_DIR = PROJECT_ROOT / "data" / "x"

# =====================================================
# MIGRATION LOGIC
# =====================================================
def migrate_file(file_path: Path) -> tuple[int, int]:
    """
    Returns:
        (updated_posts, total_posts)
    """
    with open(file_path, encoding="utf-8") as f:
        posts = json.load(f)

    updated = 0

    for post in posts:
        # Always attempt parsing (even if metrics exist)
        metrics = extract_metrics_from_text(post.get("content", ""))

        if any(v is not None for v in metrics.values()):
            post["likes"] = metrics["likes"]
            post["comments"] = metrics["comments"]
            post["shares"] = metrics["shares"]
            post["views"] = metrics["views"]
            post["metrics_source"] = "text"
            updated += 1
        else:
            # Explicitly mark unavailable metrics
            post.setdefault("metrics_source", "unavailable")

    # Write back only if something meaningful changed
    if updated > 0:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(posts, f, indent=2, ensure_ascii=False)

    return updated, len(posts)


def migrate_all():
    total_updated = 0
    total_files = 0

    print("\n🔄 Migrating X datasets...\n")

    for file in sorted(DATA_DIR.glob("*.json")):
        updated, total = migrate_file(file)

        if updated > 0:
            print(f"✔ {file.name}: {updated}/{total} posts updated")
            total_updated += updated
            total_files += 1
        else:
            print(f"⚠ {file.name}: no extractable metrics")

    print("\n✅ Migration complete")
    print(f"   Files updated : {total_files}")
    print(f"   Posts updated : {total_updated}\n")


if __name__ == "__main__":
    migrate_all()


# # =====================================================
# # FIX PYTHON PATH (MUST BE FIRST)
# # =====================================================
# import sys
# from pathlib import Path

# PROJECT_ROOT = Path(__file__).resolve().parents[1]
# sys.path.insert(0, str(PROJECT_ROOT))

# # =====================================================
# # NOW IMPORT PROJECT MODULES
# # =====================================================
# import json
# from utils.x_text_metrics import extract_metrics_from_text

# # =====================================================
# # CONFIG
# # =====================================================
# DATA_DIR = PROJECT_ROOT / "data" / "x"

# # =====================================================
# # MIGRATION LOGIC
# # =====================================================
# def migrate_file(file_path: Path) -> int:
#     with open(file_path, encoding="utf-8") as f:
#         posts = json.load(f)

#     updated = 0

#     for post in posts:
#         if (
#             post.get("likes") is None or
#             post.get("comments") is None or
#             post.get("shares") is None
#         ):
#             metrics = extract_metrics_from_text(post.get("content", ""))

#             if any(v is not None for v in metrics.values()):
#                 post["likes"] = metrics["likes"]
#                 post["comments"] = metrics["comments"]
#                 post["shares"] = metrics["shares"]
#                 updated += 1

#     if updated > 0:
#         with open(file_path, "w", encoding="utf-8") as f:
#             json.dump(posts, f, indent=2, ensure_ascii=False)

#     return updated


# def migrate_all():
#     total_files = 0
#     total_posts = 0

#     for file in DATA_DIR.glob("*.json"):
#         count = migrate_file(file)
#         if count > 0:
#             total_files += 1
#             total_posts += count
#             print(f"✔ Updated {count} posts in {file.name}")

#     print(f"\nDone. {total_posts} posts updated across {total_files} files.")


# if __name__ == "__main__":
#     migrate_all()


# import json
# from pathlib import Path
# from utils.x_text_metrics import extract_metrics_from_text

# DATA_DIR = Path("data/x")

# def migrate_file(file_path: Path) -> int:
#     with open(file_path, encoding="utf-8") as f:
#         posts = json.load(f)

#     updated = 0

#     for post in posts:
#         # Only update if metrics are missing
#         if (
#             post.get("likes") is None or
#             post.get("comments") is None or
#             post.get("shares") is None
#         ):
#             metrics = extract_metrics_from_text(post.get("content", ""))

#             # Update only if something was found
#             if any(v is not None for v in metrics.values()):
#                 post["likes"] = metrics["likes"]
#                 post["comments"] = metrics["comments"]
#                 post["shares"] = metrics["shares"]
#                 updated += 1

#     if updated > 0:
#         with open(file_path, "w", encoding="utf-8") as f:
#             json.dump(posts, f, indent=2, ensure_ascii=False)

#     return updated


# def migrate_all():
#     total_files = 0
#     total_posts = 0

#     for file in DATA_DIR.glob("*.json"):
#         count = migrate_file(file)
#         if count > 0:
#             total_files += 1
#             total_posts += count
#             print(f"✔ Updated {count} posts in {file.name}")

#     print(f"\nDone. {total_posts} posts updated across {total_files} files.")


# if __name__ == "__main__":
#     migrate_all()
