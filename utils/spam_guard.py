import re
from collections import Counter
from dataclasses import dataclass, field
from html import unescape
from typing import Any


PROMOTIONAL_PHRASES = (
    "act now",
    "apply now",
    "buy now",
    "click here",
    "don't miss",
    "free trial",
    "guaranteed",
    "limited time",
    "make money",
    "no obligation",
    "once in a lifetime",
    "risk free",
    "special offer",
    "urgent",
    "winner",
)

CTA_PHRASES = (
    "book a call",
    "schedule a call",
    "let me know",
    "reply back",
    "click here",
    "apply now",
    "sign up",
    "get started",
    "contact me",
    "reach out",
)

SUSPICIOUS_URL_PATTERNS = (
    r"https?://\d{1,3}(?:\.\d{1,3}){3}",
    r"https?://[^\s<>\"]*(?:bit\.ly|tinyurl\.com|t\.co|goo\.gl|ow\.ly|is\.gd|buff\.ly)",
    r"https?://[^\s<>\"]*@",
    r"https?://[^\s<>\"]*(?:login|verify|secure|account)[^\s<>\"]*",
)


@dataclass
class SpamRisk:
    score: float
    level: str
    action: str
    decision: str
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level,
            "action": self.action,
            "decision": self.decision,
            "reasons": self.reasons,
            "signals": self.signals,
            "raw": self.raw,
        }


def analyze_email_risk(email_subject: str, email_body: str, email_from: str = "", recipient_email: str = "") -> SpamRisk:
    text = _normalize_text(f"{email_subject}\n{_strip_html(email_body)}")
    reasons: list[str] = []
    signals: dict[str, Any] = {}
    score = 0.0

    words = re.findall(r"[A-Za-z][A-Za-z']+", text)
    alpha_chars = re.findall(r"[A-Za-z]", text)
    upper_chars = re.findall(r"[A-Z]", text)
    caps_ratio = len(upper_chars) / max(1, len(alpha_chars))
    all_caps_words = [word for word in words if len(word) >= 4 and word.isupper()]
    if caps_ratio > 0.35 or len(all_caps_words) >= 4:
        score += 2.0
        reasons.append("excessive capitalization")
    signals["caps_ratio"] = round(caps_ratio, 3)
    signals["all_caps_words"] = len(all_caps_words)

    exclamation_count = text.count("!")
    question_count = text.count("?")
    if exclamation_count >= 4 or question_count >= 4 or exclamation_count + question_count >= 6:
        score += 1.5
        reasons.append("excessive punctuation")
    signals["exclamation_count"] = exclamation_count
    signals["question_count"] = question_count

    urls = re.findall(r"https?://[^\s<>\"]+", email_body)
    if len(urls) > 2:
        score += 1.5
        reasons.append("too many links")
    suspicious_urls = [url for url in urls if _is_suspicious_url(url)]
    if suspicious_urls:
        score += 2.5
        reasons.append("suspicious URLs")
    signals["link_count"] = len(urls)
    signals["suspicious_url_count"] = len(suspicious_urls)

    lower_text = text.lower()
    phrase_hits = sorted({phrase for phrase in PROMOTIONAL_PHRASES if phrase in lower_text})
    if phrase_hits:
        score += min(2.5, 0.7 * len(phrase_hits))
        reasons.append("common spam or promotional phrases")
    signals["promotional_phrase_hits"] = phrase_hits

    urgent_hits = re.findall(r"\b(?:urgent|immediately|asap|limited|exclusive|guaranteed|free|now)\b", lower_text)
    if len(urgent_hits) >= 3:
        score += 1.5
        reasons.append("excessive promotional or urgent language")
    signals["urgent_language_count"] = len(urgent_hits)

    word_count = len(words)
    if word_count < 45:
        score += 1.0
        reasons.append("unusually short email")
    elif word_count > 260:
        score += 1.0
        reasons.append("unusually long email")
    signals["word_count"] = word_count

    repeated = _repeated_phrases(lower_text)
    if repeated:
        score += 1.5
        reasons.append("repeated phrases")
    signals["repeated_phrases"] = repeated[:5]

    cta_hits = [phrase for phrase in CTA_PHRASES if phrase in lower_text]
    if len(cta_hits) > 2:
        score += 1.5
        reasons.append("too many calls to action")
    signals["cta_count"] = len(cta_hits)

    score = round(min(score, 10.0), 2)
    if score >= 4:
        level = "MEDIUM"
        action = "REGENERATE"
        decision = "REGENERATE"
    else:
        level = "LOW"
        action = "SEND"
        decision = "PASS"

    return SpamRisk(
        score=score,
        level=level,
        action=action,
        decision=decision,
        reasons=reasons,
        signals=signals,
        raw={
            "guard": "local_spam_guard",
            "email_from": email_from,
            "recipient_email": recipient_email,
        },
    )


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return unescape(without_tags)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _is_suspicious_url(url: str) -> bool:
    return any(re.search(pattern, url, re.IGNORECASE) for pattern in SUSPICIOUS_URL_PATTERNS)


def _repeated_phrases(text: str) -> list[str]:
    tokens = re.findall(r"[a-z][a-z']+", text)
    phrases = [" ".join(tokens[index : index + 3]) for index in range(max(0, len(tokens) - 2))]
    return [phrase for phrase, count in Counter(phrases).items() if count >= 3]
