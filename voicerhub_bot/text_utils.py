import re


_EMOJI_RANGES = (
    "\U0001F000-\U0001FAFF"
    "\U0001FC00-\U0001FFFF"
    "\u2300-\u23FF"
    "\u2600-\u27BF"
    "\u2B00-\u2BFF"
)
_EMOJI_RE = re.compile(f"[{_EMOJI_RANGES}]")
_FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")
_KEYCAP_RE = re.compile(r"[#*0-9]\ufe0f?\u20e3")
_EMOJI_MODIFIER_RE = re.compile(r"[\U0001F3FB-\U0001F3FF]")
_VARIATION_AND_JOINER_RE = re.compile(r"[\ufe0e\ufe0f\u200d]")


def strip_emoji(value: str) -> str:
    result = _KEYCAP_RE.sub("", value)
    result = _FLAG_RE.sub("", result)
    result = _EMOJI_MODIFIER_RE.sub("", result)
    result = _EMOJI_RE.sub("", result)
    result = _VARIATION_AND_JOINER_RE.sub("", result)
    return " ".join(result.split())
