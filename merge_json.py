import json

# Load both versions manually saved
with open("data/news.json", "r") as f:
    content = f.read()

# Split conflict parts
parts = content.split("<<<<<<< Updated upstream")

merged_data = []

for part in parts:
    if "=======" in part and ">>>>>>>" in part:
        upstream, rest = part.split("=======")
        local, _ = rest.split(">>>>>>> Stashed changes")

        try:
            upstream_json = json.loads(upstream.strip())
            local_json = json.loads(local.strip())

            if isinstance(upstream_json, list) and isinstance(local_json, list):
                merged_data.extend(upstream_json)
                merged_data.extend(local_json)

            elif isinstance(upstream_json, dict) and isinstance(local_json, dict):
                merged_data.append({**upstream_json, **local_json})

        except:
            pass

# Remove duplicates
unique = {json.dumps(x, sort_keys=True): x for x in merged_data}
merged_data = list(unique.values())

# Save merged
with open("data/news_merged.json", "w") as f:
    json.dump(merged_data, f, indent=2)

print("Merged successfully.")