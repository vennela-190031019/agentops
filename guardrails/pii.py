"""PII redaction for emails, phone numbers and credit card numbers.

Primary path: Microsoft Presidio (presidio-analyzer + presidio-anonymizer),
pinned to spaCy's small `en_core_web_sm` model (~13MB) instead of Presidio's
default `en_core_web_lg` (~400MB) -- the default model is far too heavy for a
CI install step, the small model downloads in a few seconds and is enough for
these three entity types. If presidio/spacy/the model aren't importable
(e.g. the optional dependency wasn't installed), we fall back to plain regex
for the same three entity types so the agent keeps working either way.
"""
import re

ENTITIES = ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"]

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PHONE_RE = re.compile(r"(?<!\d)(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")

# Used to scan already-produced text (e.g. a final answer) for PII that leaked
# through unredacted. Order matters: credit card (13-19 digits) before phone
# (10-11 digits) avoids a long card number being partially reported as a phone.
_SCAN_RE = re.compile(
    f"(?:{_EMAIL_RE.pattern})|(?:{_CREDIT_CARD_RE.pattern})|(?:{_PHONE_RE.pattern})"
)

_engine = None  # (analyzer, anonymizer) once loaded, or False if unavailable


def _load_presidio():
    global _engine
    if _engine is not None:
        return _engine
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine

        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        })
        analyzer = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
        _engine = (analyzer, AnonymizerEngine())
    except Exception:
        _engine = False
    return _engine


def _regex_redact(text: str) -> tuple[str, set[str]]:
    found = set()

    def _sub(entity, pattern, s):
        def repl(m):
            found.add(entity)
            return f"<{entity}>"
        return pattern.sub(repl, s)

    text = _sub("EMAIL_ADDRESS", _EMAIL_RE, text)
    text = _sub("CREDIT_CARD", _CREDIT_CARD_RE, text)
    text = _sub("PHONE_NUMBER", _PHONE_RE, text)
    return text, found


def redact_pii(text: str) -> tuple[str, set[str]]:
    """Return (redacted_text, entity_types_found)."""
    if not text:
        return text, set()
    engine = _load_presidio()
    if engine:
        analyzer, anonymizer = engine
        results = analyzer.analyze(text=text, language="en", entities=ENTITIES)
        if not results:
            return text, set()
        out = anonymizer.anonymize(text=text, analyzer_results=results)
        return out.text, {r.entity_type for r in results}
    return _regex_redact(text)


def contains_pii(text: str) -> bool:
    """True if raw (unredacted) email/phone/credit-card-shaped text is present."""
    return bool(text) and bool(_SCAN_RE.search(text))
