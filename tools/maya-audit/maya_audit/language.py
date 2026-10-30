"""Declared page language and a small stopword-based language guess.

The guess is Estimated and deliberately conservative: it covers eight languages,
needs enough text, and needs a clear winner. Anything else is "inconclusive",
never a guess. Checks whose text heuristics are English-only use
`english_text_assessable` to report "not assessed" instead of a false pass.
"""

from __future__ import annotations

import re

from .config import MAX_NAME_WORDS, PERSONAL_TITLES, PERSONAL_TITLES_WITH_STOP

STOPWORDS = {
    "en": "the and of to in is for that with on are as this be by from or at your you it an was have not we our can will",
    "tr": "ve bir bu için ile çok olan gibi daha ne ama olarak her kadar sonra veya değil var yok şey ben biz sizin "
          "olarak göre ancak",
    "de": "der die und das ist nicht zu den mit von sich des auf für im dem ein eine auch es werden aus hat dass sie "
          "nach bei wir",
    "fr": "le la les et des est pas pour que qui dans une du sur au avec ce il sont par plus vous nous cette aux ou mais",
    "es": "el la los las y que en un una es por con para del se no al lo como más pero sus su este esta son está",
    "it": "il di che e la per un una sono non con del della le gli si da al nel è anche come più questo ma",
    "pt": "o a os as e que de do da em um uma para com não por mais se no na dos das é você ao mas",
    "nl": "de het een en van is dat op te in voor met niet zijn er maar ook als aan bij om wij u je deze wordt",
}
STOPWORD_SETS = {lang: set(words.split()) for lang, words in STOPWORDS.items()}
SUPPORTED = frozenset(STOPWORDS)
MIN_WORDS = 50
MIN_HITS = 8
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
# BCP 47 shape only (not a registry lookup): primary subtag of 2-3 letters, then subtags of 1-8 alphanumerics.
BCP47 = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{1,8})*$")
# The shape Google reads in hreflang (B04): language of 2-3 letters, an optional 4-letter script, an optional region
# of 2 letters or 3 digits. Values are case-insensitive, so the shape is tested on the folded value.
HREFLANG_SHAPE = re.compile(r"^[a-z]{2,3}(-[a-z]{4})?(-([a-z]{2}|\d{3}))?$")
# Region codes people write that ISO 3166-1 does not have, with the one they meant. Kept to real, common mistakes.
WRONG_REGIONS = {"UK": "GB"}
# Country codes written where the language code goes (G19), with the language meant: "jp" for Japanese is "ja". Only
# codes that are not themselves an ISO 639-1 language: "uk" (Ukrainian), "se" (Northern Sami) and "kr" (Kanuri) are
# real languages, so they are never flagged. Lower or upper case region codes are both fine (hreflang ignores case).
WRONG_LANGUAGES = {"jp": "ja", "cn": "zh", "gr": "el", "dk": "da", "cz": "cs", "ua": "uk"}
# Codes reserved for private use (ISO 639 qaa-qtz, ISO 3166 AA, QM-QZ, XA-XZ, ZZ): no engine maps them to a locale.
_PRIVATE_LANGUAGE = re.compile(r"^(q[a-t][a-z]|zz)$")
_PRIVATE_REGION = re.compile(r"^(AA|Q[M-Z]|X[A-Z]|ZZ)$")


def hreflang_code_problem(code: str) -> str | None:
    """Why an hreflang value is not a usable language-region code, or None when it is (x-default is usable).

    A registry lookup is not done (the full ISO tables are not shipped): the shape is checked, then two short lists of
    known mistakes (en-UK, jp) and the private-use ranges."""
    value = (code or "").strip()
    if value.casefold() == "x-default":
        return None
    if not HREFLANG_SHAPE.match(value.casefold()):
        return "not a language(-script)(-region) code: language of 2-3 letters, region of 2 letters or 3 digits"
    parts = value.split("-")
    region = parts[-1].upper() if len(parts) > 1 and len(parts[-1]) in (2, 3) else None
    if region in WRONG_REGIONS:
        return f"{region} is not a region code; use {WRONG_REGIONS[region]}"
    if parts[0].casefold() in WRONG_LANGUAGES:
        return f"{parts[0]} is a country code, not a language code; use {WRONG_LANGUAGES[parts[0].casefold()]}"
    if _PRIVATE_LANGUAGE.match(parts[0].casefold()) or (region and _PRIVATE_REGION.match(region)):
        return "a private-use or unassigned code no engine maps to a locale"
    return None
# A web address, an e-mail address, or any run without a space that has a dot between two letters ("ornek.com",
# "www.ornek.com.tr/kampanya"): its pieces ("com", "de", "it") are not words of any language (DECISIONS 194).
_DOTTED = re.compile(r"[^\W\d_]\.[^\W\d_]", re.UNICODE)
# A word with what an apostrophe joins to it: "Trendyol'da" is one word, and counts by the part before the apostrophe.
_SUFFIXED = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
# An ordinal suffix written after a number ("2.si %10 indirimli", "3'üncü", "1st", "2nd"): not a word of any language
# (DECISIONS 265; a Turkish shop's "2.si" made 31 Italian "si" and called the page Italian).
_ORDINAL = re.compile(r"(?<=\d)[.'’]?(?:s[iıuü]|[iıuü]nc[iıuü]|nc[iıuü]|st|nd|rd|th|er|e|ème|º|ª)(?![^\W\d_])", re.UNICODE)


def words_of(text: str | None) -> list[str]:
    """The words of a text as the language guesses count them (DECISIONS 194): addresses are taken out first, and a
    word with an apostrophe is the part before it ("Trendyol'da" is "Trendyol": the Turkish suffix "da" is not the
    Portuguese word "da")."""
    kept = " ".join(run for run in _ORDINAL.sub(" ", text or "").split()
                    if not ("://" in run or "@" in run or _DOTTED.search(run)))
    return [re.split("['’]", word, maxsplit=1)[0] for word in _SUFFIXED.findall(kept)]


def lower(word: str) -> str:
    """A word lower-cased for the stopword lists (B10): a capital dotted İ is the Turkish i, so "İÇİN" is "için";
    casefold() alone would give "i" and a combining dot, which no stopword matches."""
    return word.replace("İ", "i").casefold().replace("\u0307", "")


def primary_subtag(lang: str | None) -> str | None:
    if not lang:
        return None
    return re.split(r"[-_]", lang.strip(), maxsplit=1)[0].lower() or None


def detect_language(text: str, min_words: int = MIN_WORDS, declared: str | None = None) -> dict:
    """{"language": code or None, "words", "hits": {lang: n}, "reason"}; None means inconclusive.

    `declared` is the page's declared language (its primary subtag): a stopword of another language that is an
    ordinary word in the declared one (`NOT_FOREIGN_IN`: "o", "de", "da" in Turkish) is not counted for that other
    language. Words are read by `words_of`: no addresses, and a word with an apostrophe by its first part."""
    words = [lower(w) for w in words_of(text)]
    own = NOT_FOREIGN_IN.get(declared or "", frozenset())
    hits = {lang: sum(1 for w in words if w in stops and (lang == declared or w not in own)) for lang, stops in STOPWORD_SETS.items()}
    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    (top, top_hits), (_, second_hits) = ranked[0], ranked[1]
    out = {"language": None, "words": len(words), "hits": {k: v for k, v in ranked if v}, "method": "stopword counts (Estimated)"}
    if len(words) < min_words:
        out["reason"] = f"too little text ({len(words)} words, need {min_words})"
    elif top_hits < MIN_HITS:
        out["reason"] = f"too few stopwords from the {len(SUPPORTED)} supported languages ({top_hits})"
    elif top_hits < 2 * second_hits:
        out["reason"] = f"no clear winner ({top} {top_hits} vs {ranked[1][0]} {second_hits})"
    else:
        out["language"] = top
    return out


NAMES = {"en": "English", "tr": "Turkish", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
         "pt": "Portuguese", "nl": "Dutch"}


def text_assessable(analysis: dict, languages: frozenset[str] | set[str]) -> tuple[bool, str]:
    """Whether text signatures written for `languages` can be trusted to find nothing on this page.

    A confident guess wins over the declared `lang` (templates often ship lang="en" on
    translated pages); the declaration is used only when the guess is inconclusive.
    """
    declared = primary_subtag(analysis.get("html_lang"))
    guess = detect_language(analysis.get("_visible_text", ""), declared=declared)
    if guess["language"] in languages:
        return True, f"content detected as {NAMES.get(guess['language'], guess['language'])}"
    if guess["language"]:
        return False, f"content detected as {guess['language']} (declared lang={analysis.get('html_lang')!r})"
    if declared in languages:
        return True, f"declared lang={analysis.get('html_lang')!r}; language guess inconclusive"
    if declared:
        return False, f"declared lang={analysis.get('html_lang')!r}"
    return False, f"no lang declared and language guess inconclusive: {guess['reason']}"


def english_text_assessable(analysis: dict) -> tuple[bool, str]:
    """Whether English-only text signatures can be trusted to find nothing on this page."""
    return text_assessable(analysis, {"en"})


def turkish_fold(text: str) -> str:
    """Lower-case the Turkish way (İ -> i, I -> ı), so a pattern written in lower case matches "İÇİN" and "Giriş"."""
    return text.replace("İ", "i").replace("I", "ı").lower()


_TURKISH_LETTERS = re.compile(r"[çğışÇĞİŞ]")
MIN_BLOCK_WORDS = 6
MIN_HEADING_WORDS = 3


_TITLE = re.compile(
    r"(?<![^\W_])(?:(?:" + "|".join(re.escape(t) for t in sorted(PERSONAL_TITLES, key=len, reverse=True)) + r")\.?"
    r"|m\.\s?d\.?|(?:" + "|".join(re.escape(t) for t in PERSONAL_TITLES_WITH_STOP) + r")\.)(?![^\W_])", re.IGNORECASE)


def has_personal_title(text: str) -> bool:
    """Whether a heading carries a title or degree that goes with a name: "Uzm. Psk. Ayşe Yılmaz", "Pelin Taş, M.D."."""
    return bool(_TITLE.search(turkish_fold(text or "")))


def looks_like_name(text: str) -> bool:
    """A few capitalised words with no common word of any language: "Mehmet Ali Yılmaz". So is "Şizofreni Tedavi
    Yöntemleri", which is why this is used only on a page that also lists people by title (a team page)."""
    words = _WORD.findall(text or "")
    if not 2 <= len(words) <= MAX_NAME_WORDS or not all(w[0].isupper() for w in words):
        return False
    return not any(lower(w) in stops for w in words for stops in STOPWORD_SETS.values())


# Words that are evidence of a language in a heading only (a heading is often a question: "Staking nedir?").
HEADING_WORDS = {"tr": frozenset("nedir nasıl nasil neden niçin kimdir nelerdir nerede hangi kaç mi mı mu mü".split())}
# A stopword of another language that is an ordinary word in the declared one says nothing: "et" is French for "and"
# and Turkish for "do" ("Bizi Takip Et"). By declared language. An agent default, not a full list. The second line
# (DECISIONS 194) is short words and letters a Turkish page carries without being in another language: a table marker
# ("o"), a suffix written apart, a brand or a unit.
NOT_FOREIGN_IN = {"tr": frozenset(("et de da o en on an son al in ne se su si "
                                   "a e no na il van at as can para es un sus der den dem hat sur te er u").split())}
_PARENTHESES = re.compile(r"\([^()]*\)")
HEADING_METHOD = ("word lists (Estimated): a heading is called by one common word of a language when no other language "
                  "has any. Not counted: words in parentheses, a common word between two capitalised words (a term or a "
                  "name, “Proof of Stake”), and a word that is ordinary in the declared language (“et” in Turkish)")


def heading_language(text: str, among_names: bool = False, declared: str | None = None) -> str | None:
    """The language of a heading, or None. Headings are short, so one piece of evidence is enough, but only
    when no other language has any: "Information for new patient" is English, "Check-up Merkezi" is not called.

    A person's name is never called: the letters in "Çağdaş Yokuşoğlu" are Turkish, the page need not be. A
    heading with a title or degree is a name; with `among_names` (the page has such headings), so is a short
    all-capitalised heading without one.

    A term or a proper noun is not a sentence in its language (DECISIONS 174). Three things are not evidence: words
    inside parentheses ("(DPoS)"); a stopword between two capitalised words ("Proof of Stake"); and, when the page's
    `declared` language is given, a stopword of another language that is an ordinary word in the declared one. Still a
    heuristic over word lists: Estimated."""
    words = _WORD.findall(text or "")
    if len(words) < MIN_HEADING_WORDS or has_personal_title(text) or (among_names and looks_like_name(text)):
        return None
    words = _WORD.findall(_PARENTHESES.sub(" ", text or ""))
    own = NOT_FOREIGN_IN.get(declared or "", frozenset())
    hits = {lang: 0 for lang in STOPWORD_SETS}
    for at, word in enumerate(words):
        folded = lower(word)
        inside_a_term = 0 < at < len(words) - 1 and words[at - 1][:1].isupper() and words[at + 1][:1].isupper()
        for lang, stops in STOPWORD_SETS.items():
            if folded not in stops and folded not in HEADING_WORDS.get(lang, ()):
                continue
            if inside_a_term or (lang != declared and folded in own):
                continue
            hits[lang] += 1
    hits["tr"] += sum(1 for w in words if _TURKISH_LETTERS.search(w))
    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[0][0] if ranked[0][1] >= 1 and ranked[1][1] == 0 else None


def block_language(text: str) -> str | None:
    """The language of one passage, or None when it is too short or too mixed to call.

    Stopword counts over the supported languages, with the letters only Turkish uses (ç ğ ı ş) counted as
    Turkish evidence. Words are read as `detect_language` reads them (`words_of`). Needs at least MIN_BLOCK_WORDS
    words, two pieces of evidence, and a clear winner.
    """
    words = words_of(text)
    if len(words) < MIN_BLOCK_WORDS:
        return None
    folded = [lower(w) for w in words]
    hits = {lang: sum(1 for w in folded if w in stops) for lang, stops in STOPWORD_SETS.items()}
    hits["tr"] += sum(1 for w in words if _TURKISH_LETTERS.search(w))
    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    (top, top_hits), (_, second_hits) = ranked[0], ranked[1]
    return top if top_hits >= 2 and top_hits >= 2 * max(second_hits, 0.5) else None
