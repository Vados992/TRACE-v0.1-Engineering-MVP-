from difflib import SequenceMatcher

from ..models import ResolutionRecord, ResolutionResult
from .normalize import normalize_identifier, normalize_org_name, normalize_text

IDENTIFIER_SCHEMES = {"LEI", "VAT", "BRIS", "NATIONAL_COMPANY_NUMBER", "ISIN", "EU_TRANSPARENCY_ID"}


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def identifier_feature(left: ResolutionRecord, right: ResolutionRecord) -> tuple[float, list[str]]:
    reasons: list[str] = []
    left_ids = {k.upper(): normalize_identifier(v) for k, v in left.identifiers.items() if v}
    right_ids = {k.upper(): normalize_identifier(v) for k, v in right.identifiers.items() if v}
    common = set(left_ids) & set(right_ids) & IDENTIFIER_SCHEMES
    if not common:
        return 0.0, reasons
    matches = [scheme for scheme in common if left_ids[scheme] == right_ids[scheme]]
    conflicts = [scheme for scheme in common if left_ids[scheme] != right_ids[scheme]]
    if conflicts:
        reasons.append(f"conflicting strong identifiers: {', '.join(sorted(conflicts))}")
        return -1.0, reasons
    if matches:
        reasons.append(f"exact identifier match: {', '.join(sorted(matches))}")
        return 1.0, reasons
    return 0.0, reasons


def score_records(left: ResolutionRecord, right: ResolutionRecord) -> ResolutionResult:
    # Safety invariant: person records are never auto-merged from name similarity alone.
    if left.entity_type != right.entity_type:
        return ResolutionResult(score=0.0, decision="KEEP_SEPARATE", features={"type": 0.0}, reasons=["entity types differ"])

    id_score, reasons = identifier_feature(left, right)
    if id_score < 0:
        return ResolutionResult(score=0.0, decision="KEEP_SEPARATE", features={"identifier": 0.0}, reasons=reasons)

    name_left = normalize_org_name(left.name) if left.entity_type == "ORGANIZATION" else normalize_text(left.name)
    name_right = normalize_org_name(right.name) if right.entity_type == "ORGANIZATION" else normalize_text(right.name)
    name_score = similarity(name_left, name_right)
    address_score = similarity(normalize_text(left.address), normalize_text(right.address))
    jurisdiction_score = 1.0 if left.jurisdiction_code and left.jurisdiction_code == right.jurisdiction_code else 0.0
    date_score = 1.0 if left.incorporation_date and left.incorporation_date == right.incorporation_date else 0.0

    left_directors = {normalize_text(x) for x in left.directors}
    right_directors = {normalize_text(x) for x in right.directors}
    union = left_directors | right_directors
    director_score = len(left_directors & right_directors) / len(union) if union else 0.0

    features = {
        "identifier": max(id_score, 0.0),
        "name": name_score,
        "address": address_score,
        "jurisdiction": jurisdiction_score,
        "director_overlap": director_score,
        "incorporation_date": date_score,
    }

    if id_score == 1.0:
        score = 0.995
    else:
        score = (
            0.50 * name_score
            + 0.18 * address_score
            + 0.12 * jurisdiction_score
            + 0.12 * director_score
            + 0.08 * date_score
        )

    if left.entity_type == "PERSON" and id_score != 1.0:
        decision = "HUMAN_REVIEW" if score >= 0.90 else "KEEP_SEPARATE"
        reasons.append("person auto-merge disabled without a strong exact identifier")
    elif score >= 0.98:
        decision = "AUTO_MERGE"
    elif score >= 0.90:
        decision = "HUMAN_REVIEW"
    else:
        decision = "KEEP_SEPARATE"

    if name_score >= 0.95:
        reasons.append("very high normalized-name similarity")
    if address_score >= 0.90:
        reasons.append("high address similarity")
    if jurisdiction_score:
        reasons.append("same jurisdiction")
    if director_score:
        reasons.append("overlapping directors")
    if date_score:
        reasons.append("same incorporation date")

    return ResolutionResult(score=round(score, 6), decision=decision, features=features, reasons=reasons)
