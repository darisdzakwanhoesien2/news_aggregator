import json
import os
import re

INPUT_FILE = "data/news.json"
OUTPUT_FILE = "data/news_merged.json"

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Input file '{INPUT_FILE}' does not exist.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Try loading the JSON directly (if conflict markers are already resolved or do not exist)
    try:
        data = json.loads(content)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("✅ No conflict markers found. JSON file loaded and saved successfully.")
        return
    except json.JSONDecodeError:
        # File has invalid JSON, likely due to active git conflict markers
        pass

    # 2. Extract conflict segments using regex supporting arbitrary markers (e.g. HEAD, Updated upstream, Stashed changes)
    # Match: <<<<<<< [marker]\n [upstream] \n=======\n [local] \n>>>>>>> [marker]
    conflict_pattern = re.compile(
        r"<<<<<<<.*?\n(.*?)\n=======\n(.*?)\n>>>>>>>.*?(?:\n|$)",
        re.DOTALL
    )

    merged_data = []
    matches = conflict_pattern.findall(content)

    for upstream, local in matches:
        try:
            upstream_json = json.loads(upstream.strip())
            local_json = json.loads(local.strip())

            # Merge lists by appending elements
            if isinstance(upstream_json, list) and isinstance(local_json, list):
                merged_data.extend(upstream_json)
                merged_data.extend(local_json)
            # Merge dicts by combining keys
            elif isinstance(upstream_json, dict) and isinstance(local_json, dict):
                merged_data.append({**upstream_json, **local_json})
        except Exception:
            # Skip invalid json segments inside conflict block
            pass

    if not merged_data:
        print("⚠️ No valid JSON data could be recovered from conflict blocks.")
        return

    # 3. Deduplicate recovered objects (converting dicts to sorted JSON strings for comparison)
    unique = {json.dumps(x, sort_keys=True): x for x in merged_data}
    merged_data = list(unique.values())

    # 4. Save merged result
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(merged_data, f, indent=2, ensure_ascii=False)

    print(f"✅ Merged {len(merged_data)} items successfully into {OUTPUT_FILE}.")

if __name__ == "__main__":
    main()