"""Context aggregation: auto-recall relevant memory before agent runs."""

import re
from pathlib import Path
from typing import List

from core_tools._utils import load_json

# Stop words for keyword extraction (English + Czech)
_STOP_WORDS = {
    # English
    "the", "is", "it", "to", "and", "of", "in", "for", "on", "with",
    "this", "that", "are", "was", "not", "but", "what", "how", "can",
    "have", "has", "had", "will", "would", "could", "should", "been",
    "from", "they", "them", "their", "there", "then", "than", "when",
    "where", "which", "who", "whom", "whose", "some", "any", "all",
    "each", "every", "both", "more", "most", "other", "into", "over",
    "such", "only", "also", "just", "about", "very", "much", "many",
    # Czech
    "a", "ale", "ani", "asi", "bez", "bude", "budu", "by", "byl", "byla",
    "byli", "bylo", "být", "co", "jak", "jako", "je", "jeho", "jej", "její",
    "jejich", "jen", "ještě", "jí", "jiné", "jsou", "jsem", "jsi", "jsme",
    "jste", "kam", "kde", "kdo", "když", "která", "které", "který",
    "mají", "mám", "máš", "máte", "mně", "moc", "moje", "moji",
    "mohou", "možná", "můj", "musí", "může", "nad", "nam", "nám",
    "naše", "nebo", "než", "nic", "ona", "oni", "ono", "pak", "pod",
    "podle", "pro", "proč", "proto", "protože", "před", "přes", "při",
    "snad", "tak", "také", "taky", "tam", "toho", "tohle", "tom",
    "tomu", "tuto", "tvoje", "tvůj", "tyto", "už", "velmi", "ze", "že",
}

MAX_RESULTS = 10
MAX_CONTEXT_CHARS = 2000


def _extract_keywords(text: str) -> set:
    """Extract meaningful keywords from text (>3 chars, not stop words)."""
    words = set()
    for word in re.findall(r"\w+", text.lower()):
        if len(word) > 3 and word not in _STOP_WORDS:
            words.add(word)
    return words


def recall_memory(workspace: Path, text: str) -> str:
    """Search memory.json for facts relevant to the user's message.

    Returns a formatted context string to prepend to the prompt,
    or empty string if nothing relevant found.
    """
    memory_path = workspace / "data" / "memory.json"
    items: List[dict] = load_json(memory_path, [])
    if not items:
        return ""

    keywords = _extract_keywords(text)
    if not keywords:
        return ""

    seen_ids: set = set()
    results: list = []

    for keyword in keywords:
        for item in items:
            item_id = item.get("id", "")
            if item_id in seen_ids:
                continue
            if keyword in str(item.get("text", "")).lower():
                results.append(item)
                seen_ids.add(item_id)
                if len(results) >= MAX_RESULTS:
                    break
        if len(results) >= MAX_RESULTS:
            break

    if not results:
        return ""

    lines = ["[Memory context]"]
    total = 0
    for r in results:
        entry = f"- {r.get('text', '')}"
        total += len(entry)
        if total > MAX_CONTEXT_CHARS:
            break
        lines.append(entry)

    return "\n".join(lines)
