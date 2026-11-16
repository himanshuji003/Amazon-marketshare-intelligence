"""Auto-derive generic search keywords from fetched products (MODE B, when --keywords not given)."""
import re
from collections import Counter

NOISE = {
    "with", "for", "and", "the", "of", "in", "by", "a", "an", "to", "pack", "set", "combo", "new", "latest",
    "black", "white", "red", "blue", "green", "grey", "gray", "silver", "gold", "pink", "orange", "yellow", "brown",
    "watt", "watts", "w", "ltr", "litre", "liter", "l", "ml", "kg", "gm", "jar", "jars", "year", "years", "yr",
    "warranty", "stainless", "steel", "motor", "speed", "speeds", "model", "inch", "cm", "mm", "pcs", "piece",
    "pieces", "free", "gift", "upto", "up", "off", "multi", "purpose", "home", "kitchen", "heavy", "duty",
}
GENERIC_CATS = {"home & kitchen", "electronics", "home", "kitchen", "all categories", "kitchen & home appliances",
                "appliances", "amazon.in", "home & kitchen products"}


def _clean_words(text, brand):
    brand_words = set(re.findall(r"[a-z0-9]+", (brand or "").lower()))
    out = []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]*", text):
        lw = w.lower()
        if lw in NOISE or lw in brand_words or any(ch.isdigit() for ch in lw):
            continue
        out.append(lw)
    return out


def _from_title(p):
    head = re.split(r"[|,(]| - | – | with | for ", p.get("title") or "", maxsplit=1, flags=re.I)[0]
    words = _clean_words(head, p.get("brand"))
    return " ".join(words[-3:]) if words else None


def _from_category(p):
    cats = [c for c in (p.get("categories") or []) if c]
    for c in reversed(cats):
        if c.strip().lower() in GENERIC_CATS:
            continue
        words = re.findall(r"[A-Za-z]+", c.lower())
        if 1 <= len(words) <= 4:
            return " ".join(words)
    return None


def derive_keywords(products, cap=5):
    """Most common generic phrases across products, max `cap`. Category first, title as backup."""
    def norm(k):  # "mixer grinders" == "mixer grinder"
        w = k.split()
        if len(w[-1]) > 3 and w[-1].endswith("s"):
            w[-1] = w[-1][:-1]
        return " ".join(w)

    cnt, shown = Counter(), {}
    for p in products:
        for kw in (_from_category(p), _from_title(p)):
            if kw and len(kw) > 2:
                n = norm(kw)
                cnt[n] += 1
                shown.setdefault(n, kw)
    if not cnt:
        return []
    ranked = [k for k, _ in sorted(cnt.items(), key=lambda kv: (-kv[1], len(kv[0])))]
    # drop phrases fully contained in a longer chosen phrase's words (e.g. "grinder" vs "mixer grinder")
    keep = []
    for k in ranked:
        if not any(set(k.split()) < set(o.split()) for o in ranked if o != k):
            keep.append(k)
    return [shown[n] for n in keep[:cap]]
