import json
from pathlib import Path

# =========================================================
# CONFIG
# =========================================================

INPUT_FILE = Path("data/esg_keywords_v2.json")
OUTPUT_FILE = Path("data/esg_keywords_flat.json")

# Optional: limit number of keywords per company
MAX_KEYWORDS_PER_COMPANY = None   # or set to 50


# =========================================================
# LOAD ENRICHED DATA
# =========================================================

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    enriched_data = json.load(f)


# =========================================================
# CONVERSION LOGIC
# =========================================================

def extract_keywords(enriched_record):
    """
    Extract expanded_keywords from enriched record safely.
    """
    keywords = enriched_record.get("expanded_keywords", [])

    # Normalize: strip spaces + lowercase (optional)
    clean = sorted({
        kw.strip()
        for kw in keywords
        if isinstance(kw, str) and kw.strip()
    })

    if MAX_KEYWORDS_PER_COMPANY:
        clean = clean[:MAX_KEYWORDS_PER_COMPANY]

    return clean


flat_keywords = {}

for company_code, enriched_record in enriched_data.items():
    flat_keywords[company_code] = extract_keywords(enriched_record)


# =========================================================
# SAVE OUTPUT
# =========================================================

OUTPUT_FILE.parent.mkdir(exist_ok=True)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(flat_keywords, f, indent=2, ensure_ascii=False)

print("✅ Conversion completed successfully")
print(f"Input file:  {INPUT_FILE}")
print(f"Output file: {OUTPUT_FILE}")
print(f"Companies:   {len(flat_keywords)}")
