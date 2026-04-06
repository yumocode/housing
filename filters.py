import re


def extract_price(text: str) -> int | None:
    matches = re.findall(r"\$(\d{3,4})", text)
    if matches:
        return int(matches[0])
    return None
