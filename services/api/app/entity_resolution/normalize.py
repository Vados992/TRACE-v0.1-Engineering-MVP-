import re
import unicodedata

LEGAL_SUFFIXES = {
    "ag",
    "sa",
    "sas",
    "sarl",
    "gmbh",
    "bv",
    "nv",
    "ltd",
    "limited",
    "plc",
    "llc",
    "inc",
    "corp",
    "corporation",
    "spa",
    "srl",
    "oy",
    "ab",
    "as",
    "a/s",
    "se",
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def normalize_org_name(value: str | None) -> str:
    tokens = normalize_text(value).split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_identifier(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()
