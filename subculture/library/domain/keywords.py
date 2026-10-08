"""Title normalization and work-keyword matching (pure rules, no I/O)."""

import re
import unicodedata


def normalized(value):
    # Treat colon as a word break so "붕괴:스타레일" / "붕괴: 스타레일" / "Re:제로" match.
    text = unicodedata.normalize("NFKC", value).casefold().replace(":", " ")
    return " ".join(text.split())


def clean_name(value):
    value = value.strip()
    if not value or len(value) > 200:
        raise ValueError("이름은 1~200자로 입력해주세요.")
    return value


def item_title_text(data):
    """Normalized title string used for work keyword matching."""
    return normalized(" ".join(str(data.get(k) or "") for k in ("title", "titleKo")))


BRACKET_TOKEN = re.compile(r"[【\[『「]([^】\]』」]{1,30})[】\]』」]")


def work_keywords(work):
    """Display keywords: canonical name plus aliases (comma- or newline-separated)."""
    aliases = work.get("aliases") or ""
    if isinstance(aliases, list):
        parts = aliases
    else:
        parts = re.split(r"[,\n]", aliases)
    names = []
    seen = set()
    for raw in [work.get("name") or "", *parts]:
        name = (raw or "").strip()
        if not name:
            continue
        key = normalized(name)
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def keyword_pattern(keyword):
    """Compiled pattern for one keyword against normalized title text; None if it is too short."""
    alias = normalized(keyword)
    # Short aliases are noisy; ASCII aliases must not sit inside another Latin word or number.
    # Hangul/kana next to them is fine: shop titles often glue the name to a product noun.
    if len(alias) < 2:
        return None
    pattern = re.escape(alias)
    if alias.isascii():
        pattern = r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])"
    return re.compile(pattern)


def match_keyword(text, keyword):
    """Return the matched keyword if it appears in normalized title text, else None."""
    pattern = keyword_pattern(keyword)
    if pattern and pattern.search(text):
        return keyword.strip()
    return None


def compile_works(works):
    """(name, patterns) per work, ready for match_works. Entries repeating a name are merged."""
    merged = {}
    for work in works:
        name = (work.get("name") or "").strip()
        if not name:
            continue
        patterns = merged.setdefault(normalized(name), (name, []))[1]
        patterns.extend(pattern for pattern in map(keyword_pattern, work_keywords(work)) if pattern)
    return list(merged.values())


def match_works(data, compiled):
    """Names of the works whose keywords appear in the item's title, in catalog order."""
    text = item_title_text(data)
    return [name for name, patterns in compiled if any(pattern.search(text) for pattern in patterns)]
