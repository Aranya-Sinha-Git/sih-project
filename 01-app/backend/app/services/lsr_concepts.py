"""Curated nomination vocabulary, NOT reference text or proof of a violation.

Patterns require hazard phrases or bounded relationships within a clause.
Only RetrievalService can resolve nominations to official catalog evidence.
"""
import re
import unicodedata

ALIAS_VERSION = "lsr-concepts-v1"
OBJECT = r"(?:objects?|panels?|tools?|debris|materials?|pipes?|bolts?|equipment|loads?)"
PERSON = r"(?:worker|person|technician|operator|employee|rigger|pedestrian)s?"
GAP = r"(?:\s+[\w~]+){0,6}\s+"

CONCEPTS = {
    "Line of Fire": [
        rf"(?:dropped|falling|dislodged|overhead)\s+(?:facade\s+)?{OBJECT}",
        rf"{OBJECT}{GAP}(?:fell|falls|falling|dropped|dislodged)\b",
        rf"(?:loose|hanging){GAP}{OBJECT}{GAP}(?:overhead|above|strike|struck)",
        rf"{OBJECT}{GAP}(?:hanging|loose){GAP}(?:overhead|above|strike|struck)",
        rf"(?:loose|hanging)\s+{OBJECT}{GAP}(?:strike|struck)",
        r"suspended\s+(?:crane\s+)?loads?",
        r"(?:struck[ -]by|release path|line of fire|pinch point)",
        rf"(?:release|object|load|projectile)\s+(?:path|trajectory)",
        rf"{PERSON}{GAP}(?:near|under|between|behind|in front of){GAP}(?:moving|reversing)\s+(?:equipment|vehicle|truck|forklift)",
        r"moving equipment exposure",
    ],
    "Working at Height": [
        r"(?:working|work|worked)\s+at\s+height",
        r"(?:without|no|missing|absent|inadequate)\s+(?:a\s+)?(?:fall protection|safety harness|harness)",
        r"fall protection\s+(?:was\s+)?(?:absent|missing|failed)",
        rf"{PERSON}{GAP}(?:fell|falling|working|worked|climbing){GAP}(?:scaffold|ladder|roof|height|platform|edge)",
    ],
    "Safe Mechanical Lifting": [
        r"(?:crane|hoist)\s+operations?",
        r"(?:crane|hoist)\s+(?:load|lift|lifting|operation|operations)",
        r"(?:lifting|hoisting)\s+(?:operation|operations|load|loads)",
        r"(?:suspended\s+(?:crane\s+)?load|mechanical lifting)",
        r"(?:sling|rigging|hoist)\s+(?:failed|broke|failure)",
        r"crane\s+(?:was\s+)?(?:lifting|hoisting|lowering)",
    ],
    "Energy Isolation": [
        r"(?:failed|incomplete|missing|unverified)\s+(?:energy\s+)?isolation",
        r"isolation\s+(?:(?:was|is)\s+)?(?:not verified|incomplete|failed|failure|gap)",
        r"(?:without|no)\s+(?:energy\s+)?isolation(?!\s+(?:failure|gap|problem))",
        r"not\s+(?:completely\s+|fully\s+)?isolated",
        r"(?:lockout|tagout)\s+(?:failed|missing|failure)",
        r"(?:unexpected|uncontrolled)\s+(?:energization|energisation|startup|release of stored energy)",
        r"(?:contact|contacted|touching|touched)\s+(?:with\s+)?(?:a\s+)?(?:live|energized|energised)\s+(?:wire|conductor|circuit)",
    ],
    "Driving": [
        r"(?:driving|vehicle)\s+(?:operation|operations|movement|safety)",
        r"journey\s+management",
        r"(?:driver|driving)\s+(?:was\s+)?(?:speeding|distracted|fatigued|without a seatbelt)",
        r"(?:truck|vehicle|car|tanker)\s+(?:collision|collided|crashed|overturned|rollover)",
        r"(?:driving|drove)\s+(?:while\s+)?(?:texting|intoxicated)",
        r"(?:driver|passenger)\s+(?:was\s+)?(?:not wearing|without)\s+(?:a\s+)?seat\s?belt",
    ],
    "Confined Space": [
        r"confined\s+space",
        r"confined\s+space\s+(?:entry|entered|exposure)",
        rf"(?:entered|entering|inside){GAP}(?:tank|vessel|manhole|silo|confined space)",
    ],
    "Hot Work": [
        r"hot\s+work",
        r"(?:welding|welded|torch cutting|flame cutting)",
        r"(?:grinding|sparks){GAP}(?:flammable|flammables|vapour|vapor|fuel)",
    ],
    "Work Authorisation": [
        r"(?:without|no|missing|expired|invalid)\s+(?:a\s+)?(?:work\s+)?permit",
        r"permit\s+(?:(?:was|is)\s+)?(?:missing|expired|invalid|bypass|violation)",
        r"(?:work|job)\s+(?:began|started|continued)\s+without\s+authori[sz]ation",
    ],
    "Bypassing Safety Controls": [
        r"(?:bypassed|disabled|overrode|defeated)\s+(?:the\s+|a\s+)?(?:safety\s+)?(?:interlock|guard|alarm|control|trip)",
        r"(?:interlock|guard|alarm|safety control|trip)\s+(?:was\s+)?(?:bypassed|disabled|overridden|defeated)",
        r"(?:control|procedure)\s+bypass",
    ],
}


def concept_matches(narrative: str) -> dict[str, list[str]]:
    """Return original report clauses, preserving evidence apart from aliases.

    Negation is local to a clause so a safe control in one clause cannot hide
    an independently reported failure in another. Safe mentions are not failures.
    """
    matches: dict[str, list[str]] = {}
    for clause in re.split(r"(?<=[.!?;])\s+|\n+|\bbut\b", narrative):
        normalized = unicodedata.normalize("NFKD", clause.casefold())
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))
        for rule, patterns in CONCEPTS.items():
            for pattern in patterns:
                for hit in re.finditer(r"\b(?:" + pattern + r")\b", normalized):
                    if rule == 'Line of Fire' and re.search(r"\b(?:not|never)\b", hit.group()):
                        continue
                    prefix = normalized[max(0, hit.start() - 45):hit.start()]
                    if re.search(r"\b(?:no|not|never|no evidence of)\s+(?:(?:\w+)\s+){0,2}$", prefix):
                        continue
                    matches.setdefault(rule, [])
                    if clause.strip() not in matches[rule]:
                        matches[rule].append(clause.strip())
    return matches
