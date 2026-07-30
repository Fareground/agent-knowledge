"""Text analysis for lexical retrieval: tokenize → drop stopwords → stem.

Deliberately dependency-free and deterministic (no model, no data files) so it
stays inside the model-free core. Stemming collapses inflections so a task
phrased "building the deck" matches a claim about "build" — the single biggest
accuracy win for keyword retrieval — using a compact, faithful implementation
of the Porter stemming algorithm (M.F. Porter, 1980).
"""
from __future__ import annotations

# A small, high-value English stoplist. Kept short on purpose: over-aggressive
# stoplists hurt short technical statements more than they help.
STOPWORDS = frozenset("""
a an and are as at be but by for from has have how i in into is it its of on
or that the their then there these they this to was were what when which who
will with you your
""".split())


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, order preserved (BM25 needs counts)."""
    return [t for t in "".join(
        c if c.isalnum() else " " for c in text.lower()).split() if t]


def analyze(text: str, *, stem: bool = True,
            remove_stopwords: bool = True) -> list[str]:
    """The full pipeline a retriever indexes and queries on."""
    out: list[str] = []
    for tok in tokenize(text):
        if remove_stopwords and tok in STOPWORDS:
            continue
        out.append(stem_word(tok) if stem else tok)
    return out


# -- Porter stemmer ----------------------------------------------------------

_VOWELS = frozenset("aeiou")


def _is_consonant(word: str, i: int) -> bool:
    ch = word[i]
    if ch in _VOWELS:
        return False
    if ch == "y":
        return i == 0 or not _is_consonant(word, i - 1)
    return True


def _measure(stem: str) -> int:
    """The Porter measure m: the number of vowel→consonant transitions."""
    m = 0
    prev_c = True
    for i in range(len(stem)):
        c = _is_consonant(stem, i)
        if prev_c and not c:
            prev_c = False
        elif not prev_c and c:
            m += 1
            prev_c = True
    return m


def _has_vowel(stem: str) -> bool:
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _double_consonant_end(word: str) -> bool:
    return (len(word) >= 2 and word[-1] == word[-2]
            and _is_consonant(word, len(word) - 1))


def _cvc(word: str) -> bool:
    """True if word ends consonant-vowel-consonant and the last isn't w/x/y —
    the shape that takes an 'e' back on short words (hop→hopping)."""
    if len(word) < 3:
        return False
    if not (_is_consonant(word, len(word) - 3)
            and not _is_consonant(word, len(word) - 2)
            and _is_consonant(word, len(word) - 1)):
        return False
    return word[-1] not in "wxy"


def _replace_suffix(word: str, suffix: str, repl: str) -> str:
    return word[: len(word) - len(suffix)] + repl if suffix else word + repl


def stem_word(word: str) -> str:
    """Porter-stem a single lowercased token (a no-op below 3 chars)."""
    if len(word) <= 2:
        return word
    w = word

    # Step 1a — plurals.
    if w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("ies"):
        w = w[:-2]
    elif w.endswith("ss"):
        pass
    elif w.endswith("s"):
        w = w[:-1]

    # Step 1b — -ed / -ing.
    step1b_flag = False
    if w.endswith("eed"):
        if _measure(w[:-3]) > 0:
            w = w[:-1]
    elif w.endswith("ed") and _has_vowel(w[:-2]):
        w = w[:-2]
        step1b_flag = True
    elif w.endswith("ing") and _has_vowel(w[:-3]):
        w = w[:-3]
        step1b_flag = True
    if step1b_flag:
        if w.endswith(("at", "bl", "iz")):
            w += "e"
        elif _double_consonant_end(w) and w[-1] not in "lsz":
            w = w[:-1]
        elif _measure(w) == 1 and _cvc(w):
            w += "e"

    # Step 1c — y → i.
    if w.endswith("y") and _has_vowel(w[:-1]):
        w = w[:-1] + "i"

    # Step 2.
    step2 = {
        "ational": "ate", "tional": "tion", "enci": "ence", "anci": "ance",
        "izer": "ize", "abli": "able", "alli": "al", "entli": "ent",
        "eli": "e", "ousli": "ous", "ization": "ize", "ation": "ate",
        "ator": "ate", "alism": "al", "iveness": "ive", "fulness": "ful",
        "ousness": "ous", "aliti": "al", "iviti": "ive", "biliti": "ble",
    }
    for suf, repl in step2.items():
        if w.endswith(suf):
            if _measure(w[: len(w) - len(suf)]) > 0:
                w = _replace_suffix(w, suf, repl)
            break

    # Step 3.
    step3 = {"icate": "ic", "ative": "", "alize": "al", "iciti": "ic",
             "ical": "ic", "ful": "", "ness": ""}
    for suf, repl in step3.items():
        if w.endswith(suf):
            if _measure(w[: len(w) - len(suf)]) > 0:
                w = _replace_suffix(w, suf, repl)
            break

    # Step 4.
    step4 = ("al", "ance", "ence", "er", "ic", "able", "ible", "ant",
             "ement", "ment", "ent", "ou", "ism", "ate", "iti", "ous",
             "ive", "ize")
    for suf in step4:
        if w.endswith(suf):
            stem = w[: len(w) - len(suf)]
            if _measure(stem) > 1:
                if suf == "ion" and stem and stem[-1] not in "st":
                    break
                w = stem
            break
    else:
        if w.endswith("ion") and _measure(w[:-3]) > 1 and w[-4] in "st":
            w = w[:-3]

    # Step 5a — trailing e.
    if w.endswith("e"):
        stem = w[:-1]
        m = _measure(stem)
        if m > 1 or (m == 1 and not _cvc(stem)):
            w = stem

    # Step 5b — collapse double l.
    if _measure(w) > 1 and _double_consonant_end(w) and w.endswith("l"):
        w = w[:-1]

    return w
