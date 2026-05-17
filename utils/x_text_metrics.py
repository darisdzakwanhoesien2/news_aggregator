import re
from typing import Dict, Optional

MULTIPLIERS = {
    "K": 1_000,
    "M": 1_000_000,
    "B": 1_000_000_000,
}

def _parse_number(token: str) -> Optional[int]:
    token = token.replace(",", "").upper()

    match = re.fullmatch(r"(\d+(?:\.\d+)?)([KMB]?)", token)
    if not match:
        return None

    value, suffix = match.groups()
    return int(float(value) * MULTIPLIERS.get(suffix, 1))


def extract_metrics_from_text(text: str) -> Dict[str, Optional[int]]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    numbers = []
    for line in lines:
        n = _parse_number(line)
        if n is not None:
            numbers.append(n)

    metrics = {
        "comments": None,
        "shares": None,
        "likes": None,
        "views": None,
    }

    # replies, reposts, likes
    if len(numbers) >= 3:
        metrics["comments"] = numbers[-3]
        metrics["shares"] = numbers[-2]
        metrics["likes"] = numbers[-1]

    # replies, reposts, likes, views
    if len(numbers) >= 4:
        metrics["views"] = numbers[-1]
        metrics["likes"] = numbers[-2]
        metrics["shares"] = numbers[-3]
        metrics["comments"] = numbers[-4]

    return metrics


# import re
# from typing import Dict, Optional

# MULTIPLIERS = {
#     "K": 1_000,
#     "M": 1_000_000,
#     "B": 1_000_000_000,
# }

# def _parse_number(token: str) -> Optional[int]:
#     """
#     Convert '3.1K', '700K', '2M', '220' → int
#     """
#     token = token.replace(",", "").upper()

#     match = re.fullmatch(r"(\d+(?:\.\d+)?)([KMB]?)", token)
#     if not match:
#         return None

#     value, suffix = match.groups()
#     value = float(value)

#     return int(value * MULTIPLIERS.get(suffix, 1))


# def extract_metrics_from_text(text: str) -> Dict[str, Optional[int]]:
#     """
#     Extract X metrics from raw text.
#     Assumes metrics appear as numeric tokens near the bottom.
#     """
#     lines = [l.strip() for l in text.splitlines() if l.strip()]

#     numbers = []
#     for line in lines:
#         n = _parse_number(line)
#         if n is not None:
#             numbers.append(n)

#     metrics = {
#         "comments": None,
#         "shares": None,
#         "likes": None,
#         "views": None,
#     }

#     # Common X patterns:
#     # replies, reposts, likes
#     if len(numbers) >= 3:
#         metrics["comments"] = numbers[-3]
#         metrics["shares"] = numbers[-2]
#         metrics["likes"] = numbers[-1]

#     # Sometimes views is included
#     if len(numbers) >= 4:
#         metrics["views"] = numbers[-1]
#         metrics["likes"] = numbers[-2]
#         metrics["shares"] = numbers[-3]
#         metrics["comments"] = numbers[-4]

#     return metrics


# import re
# from typing import Dict

# def extract_metrics_from_text(text: str) -> Dict[str, int | None]:
#     """
#     Extract reply, repost, like, bookmark/view counts
#     from raw tweet text scraped via Playwright.

#     Assumes metrics appear as standalone numbers
#     at the end of the text block.
#     """
#     lines = [l.strip() for l in text.splitlines() if l.strip()]

#     # Collect numeric-only lines
#     numbers = []
#     for line in lines:
#         if re.fullmatch(r"\d{1,3}(?:,\d{3})*", line):
#             numbers.append(int(line.replace(",", "")))

#     metrics = {
#         "comments": None,   # replies
#         "shares": None,     # reposts
#         "likes": None,
#         "bookmarks": None,
#         "views": None
#     }

#     # X common patterns:
#     # replies, reposts, likes
#     if len(numbers) >= 3:
#         metrics["comments"] = numbers[-3]
#         metrics["shares"] = numbers[-2]
#         metrics["likes"] = numbers[-1]

#     # Some layouts include bookmarks or views
#     if len(numbers) == 4:
#         metrics["bookmarks"] = numbers[-1]
#         metrics["likes"] = numbers[-2]
#         metrics["shares"] = numbers[-3]
#         metrics["comments"] = numbers[-4]

#     if len(numbers) >= 5:
#         metrics["views"] = numbers[-1]

#     return metrics
