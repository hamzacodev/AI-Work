"""Layer 1 of the Safety Guard: fast rules. Plain Python, no AI.

A vendor message is first CLEANED (so tricks like "i g n o r e", look-alike letters,
hidden characters and leetspeak do not hide it) and then checked by many rules.

Each rule gives one of these verdicts, from mild to severe:
    sensitive_request  asks for your budget, address, phone, ID, or to move off the platform
    suspicious_link    a link, file, QR code or app install (the agent never opens these)
    payment_risk       advance payment, wire, crypto, card or login details, upfront fees
    injection          instructions aimed at the AI, role changes, secrecy from the owner

The strongest verdict wins. Layer 2 (the model) can only make it stronger, never weaker.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from app.guardrails.limit_checker import find_payment_commitments

Verdict = Literal["ok", "sensitive_request", "suspicious_link", "payment_risk", "injection"]
SEVERITY: dict[str, int] = {"ok": 0, "sensitive_request": 1, "suspicious_link": 2, "payment_risk": 3, "injection": 4}

MAX_MESSAGE_CHARS = 4000  # longer messages are not checked, they go to the user

# ---------------------------------------------------------------- cleaning

_HOMOGLYPHS = str.maketrans(
    {
        # Cyrillic and Greek letters that look like Latin ones
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ј": "j", "ѕ": "s",
        "ԁ": "d", "һ": "h", "ӏ": "l", "ԛ": "q", "ԝ": "w", "ο": "o", "α": "a", "ε": "e", "ι": "i", "ν": "v",
        "κ": "k", "τ": "t", "υ": "u", "ρ": "p", "β": "b", "ɡ": "g", "ı": "i",
    }
)  # fmt: skip
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i", "|": "l", "+": "t"})
# zero-width joiner, left/right marks, variation selector: normal in emoji and right-to-left text
_KEEP_HIDDEN = {chr(0x200D), chr(0x200E), chr(0x200F), chr(0xFE0F), "\n", "\r", "\t"}
_SPACED_RUN = re.compile(r"(?<![a-z])(?:[a-z][ .\-_*]){3,}[a-z](?![a-z])")
_EMAIL = re.compile(r"\S+@\S+\.\S+")


@dataclass(frozen=True)
class Cleaned:
    raw: str  # hidden characters removed, case kept
    plain: str  # lower case, look-alike letters mapped, accents removed, spaces collapsed
    leet: str  # plain with 1gn0re -> ignore
    spaced: str  # leet with "i g n o r e" -> "ignore"
    joined: str  # letters only, "ignoreyourrules"
    hidden_chars: int  # how many invisible characters were removed


def clean(text: str) -> Cleaned:
    hidden = 0
    kept = []
    for ch in text:
        if unicodedata.category(ch) in ("Cf", "Cc") and ch not in _KEEP_HIDDEN:
            hidden += 1
            continue
        kept.append(ch)
    raw = unicodedata.normalize("NFKC", "".join(kept))

    letters = []
    for ch in raw.translate(_HOMOGLYPHS).lower():
        if ord(ch) < 0x250:  # strip accents from Latin letters only
            ch = "".join(c for c in unicodedata.normalize("NFD", ch) if unicodedata.category(c) != "Mn")
        letters.append(ch)
    plain = re.sub(r"\s+", " ", "".join(letters)).strip()
    leet = plain.translate(_LEET)
    spaced = _SPACED_RUN.sub(lambda m: re.sub(r"[ .\-_*]", "", m.group(0)), leet)
    spaced = re.sub(r"\s+", " ", spaced)
    joined = re.sub(r"[^a-z]", "", leet)
    return Cleaned(raw, plain, leet, spaced, joined, hidden)


# ---------------------------------------------------------------- rules


@dataclass(frozen=True)
class Rule:
    id: str
    verdict: Verdict
    reason: str
    pattern: re.Pattern[str]
    views: tuple[str, ...] = ("plain", "leet", "spaced")


def _r(rid: str, verdict: Verdict, reason: str, pattern: str, views=("plain", "leet", "spaced"), flags=re.IGNORECASE) -> Rule:
    return Rule(rid, verdict, reason, re.compile(pattern, flags), views)


_OBJ = r"(?:rules?|instructions?|guidelines?|prompts?|directions?|restrictions?|constraints?|policies|guardrails?|programming|training|safeguards?|limits?|filters?|safety)"

RULES: list[Rule] = [
    # ---------------- injection: instructions aimed at the AI
    _r("inj_ignore_rules", "injection", "tells the AI to ignore its rules",
       rf"\b(?:ignore|disregard|forget|override|bypass|skip|drop|discard|cancel|disable|turn\s+off|stop\s+following|violate|break)\b.{{0,40}}\b{_OBJ}\b"),
    _r("inj_forget_everything", "injection", "tells the AI to forget everything",
       r"\b(?:ignore|disregard|forget)\b.{0,25}\b(?:everything|all)\b.{0,15}\b(?:above|before|you\s+(?:were|have\s+been)\s+(?:told|given|taught)|so\s+far)\b"),
    _r("inj_new_role", "injection", "tries to change the AI's role",
       r"\byou\s+are\s+now\s+(?:a|an|the|my|dan|called|named|acting|playing|unrestricted|allowed\s+to|no\s+longer|in\s+\w+\s+mode)\b"),
    _r("inj_pretend", "injection", "asks the AI to pretend or role-play",
       r"\b(?:pretend\s+(?:to\s+be|you\s+are|that\s+you)|role\s?-?play|play\s+the\s+role|imagine\s+you\s+are|(?:act|behave|respond|reply|answer)\s+as\s+(?:if|though|a|an|the|my))\b"),
    _r("inj_from_now_on", "injection", "tries to set new standing orders",
       r"\bfrom\s+now\s+on,?\s+(?:you\s+)?(?:must|will|shall|should|are\s+to|always|only)\b.{0,30}\b(?:accept|agree|respond|reply|answer|say|obey|follow|ignore|act|approve|pay|send)\b"),
    _r("inj_force_accept", "injection", "tries to force the AI to accept",
       r"\b(?:accept|agree\s+to|approve|confirm|take)\b.{0,30}\b(?:any|whatever|every|all)\b.{0,15}\b(?:price|offer|deal|amount|terms)\b"),
    _r("inj_no_matter_what", "injection", "tries to force the AI to accept whatever happens",
       r"\b(?:accept|agree|approve|confirm|pay)\b.{0,50}\bno\s+matter\s+(?:what|the|how)\b|\bno\s+matter\s+what\b.{0,30}\b(?:accept|agree|approve|pay)\b"),
    _r("inj_without_checking", "injection", "tries to skip the owner's approval",
       r"\b(?:accept|agree|approve|confirm|pay|buy)\b.{0,40}\bwithout\s+(?:checking|asking|confirming|approval|permission|consulting|telling|the\s+(?:owner|user|buyer)|your\s+(?:owner|user|boss)|limits?)\b"),
    _r("inj_you_must_accept_now", "injection", "orders the AI to accept immediately",
       r"\byou\s+(?:must|have\s+to|need\s+to|shall)\s+(?:accept|agree|approve|confirm)\b.{0,30}\b(?:now|immediately|right\s+away|instantly|without)\b"),
    _r("inj_reveal_prompt", "injection", "asks for the AI's hidden instructions",
       r"\b(?:your|the)\s+(?:system|hidden|initial|original|secret|internal|developer)\s+(?:prompt|message|instructions?|rules|configuration)\b"),
    _r("inj_repeat_instructions", "injection", "asks the AI to repeat its instructions",
       r"\b(?:repeat|print|reveal|show|output|display|leak|recite|dump)\b.{0,25}\b(?:your|the)\b.{0,15}\b(?:prompt|instructions|rules|guidelines)\b|\bwhat\s+(?:were|are)\s+you\s+(?:told|instructed|programmed|trained)\b"),
    _r("inj_fake_authority_line", "injection", "pretends to be a system or admin message",
       r"(?:^|\n|\.\s)\s*(?:system|admin|administrator|developer|root|assistant|dealdesk)\s*(?:message|note|override|instruction|command|prompt)?\s*[:>\]\-]\s*\w", ("plain",)),
    _r("inj_fake_authority", "injection", "claims to be the admin, developer or the AI's owner",
       r"\b(?:(?:i\s+am|this\s+is|i'm)\s+(?:the\s+)?(?:admin|administrator|developer|system\s+admin|dealdesk\s+(?:admin|team|support|developer|staff))|message\s+from\s+(?:the\s+)?(?:admin|developer|system|dealdesk\w*)|i\s+am\s+your\s+(?:owner|creator|boss|master|operator|developer))\b"),
    _r("inj_special_mode", "injection", "asks for a special or jailbreak mode",
       r"\b(?:developer|debug|god|admin|maintenance|unrestricted|jailbreak(?:en)?)\s+mode\b|\bjailbreak\b|\bsudo\b|\boverride\s+(?:code|mode|protocol|command)\b|\bauthori[sz]ation\s+code\b"),
    _r("inj_dan", "injection", "uses the DAN jailbreak name", r"\bDAN\b", ("raw",), flags=0),
    _r("inj_format_tags", "injection", "contains prompt or chat-format tags",
       r"</?\s*(?:vendor_message|system|assistant|instructions?|prompt|sys)\b[^>]*>|\[/?(?:inst|sys|system)\]|<\|[a-z_]+\|>|\bbegin\s+(?:system|new)\s+(?:prompt|instructions)\b|^\s*#{2,}\s*(?:system|instruction|assistant)", ("plain",)),
    _r("inj_end_of_input", "injection", "tries to end the vendor message early",
       r"\b(?:end|stop)\s+of\s+(?:the\s+)?(?:vendor\s+)?(?:message|input|text|prompt)\b|-{3,}\s*(?:new|system)\b"),
    _r("inj_new_instructions", "injection", "gives the AI new instructions",
       r"\b(?:new|updated|revised|additional)\s+(?:instructions?|directive|system\s+prompt)\b|\bdo\s+not\s+(?:follow|obey|listen\s+to)\b.{0,20}\b(?:your|the|previous|owner|user)\b|\b(?:stop|quit)\s+(?:following|obeying)\b"),
    _r("inj_secrecy", "injection", "asks the AI to hide something from its owner",
       r"\b(?:don'?t|do\s+not|never)\s+(?:tell|inform|notify|show|mention|alert)\b.{0,25}\b(?:owner|user|buyer|boss|master|anyone|anybody)\b|\bkeep\s+(?:this|it)\s+(?:a\s+)?secret\b|\bbetween\s+(?:us|you\s+and\s+me)\b"),
    _r("inj_decode", "injection", "asks the AI to decode and follow hidden text",
       r"\b(?:decode|decrypt|translate|unscramble)\b.{0,30}\b(?:and\s+(?:follow|execute|run|obey|do)|then\s+(?:follow|execute|run|obey|do))\b|\b(?:base64|rot13)\b.{0,30}\b(?:decode|follow|execute|instruction)"),
    _r("inj_base64_blob", "injection", "contains a long hidden-looking encoded block",
       r"[A-Za-z0-9+/]{80,}={0,2}", ("raw",), flags=0),
    # multilingual injection
    _r("inj_roman_urdu", "injection", "tells the AI to ignore its rules (Roman Urdu or Hindi)",
       r"\b(?:apni|apne|apna|aap\s+ki|aap\s+ke|tum\s+apni|tumhare|apki)\s+(?:rules?|hidayat\w*|instructions?|qawaid|niyam|ahkam)\b.{0,30}\b(?:ignore|bhool\w*|bhul\w*|nazar\s*andaz|chor\w*|chhor\w*|tod\w*|bypass)\b|\b(?:rules?|hidayat\w*|instructions?)\b.{0,25}\b(?:ignore|bhool\w*|nazar\s*andaz|chor\s*do|chhor\s*do|mat\s+mano|na\s+mano)\b|\b(?:ab\s+se\s+tum|tum\s+ab)\b.{0,20}\b(?:ho|ban)\b"),
    _r("inj_roman_urdu_accept", "injection", "tells the AI to accept any price (Roman Urdu)",
       r"\b(?:koi\s+bhi|kuch\s+bhi|har)\s+(?:price|qeemat|rate|offer)\b.{0,25}\b(?:accept|manzoor|qabool|maan)\b|\b(?:accept|manzoor|qabool)\s+kar\s*(?:do|lo|lena)\b.{0,25}\b(?:chahe|chahay|kuch\s+bhi|har\s+haal)\b"),
    _r("inj_urdu_script", "injection", "tells the AI to ignore its rules (Urdu script)",
       r"(?:نظر\s*انداز|بھول\s*جاؤ|بھول\s*جائیں).{0,25}(?:ہدایات|قواعد|اصول|ہدایت|احکامات)|(?:ہدایات|قواعد|اصول).{0,25}(?:نظر\s*انداز|بھول)", ("raw",), flags=0),
    _r("inj_arabic", "injection", "tells the AI to ignore its rules (Arabic)",
       r"(?:تجاهل|انس|تخطى).{0,25}(?:التعليمات|القواعد|الأوامر|القيود)", ("raw",), flags=0),
    _r("inj_spanish_french_german", "injection", "tells the AI to ignore its rules (Spanish, French or German)",
       r"\b(?:ignora|ignorar|olvida|ignore|oublie|ignoriere|vergiss)\b.{0,25}\b(?:instrucciones|reglas|instructions|r[eè]gles|anweisungen|regeln)\b"),
    # ---------------- sensitive requests
    _r("sens_budget", "sensitive_request", "asks for your budget or limit",
       r"\b(?:what(?:'?s|\s+is|\s+are)?|tell\s+me|share|reveal|disclose|state|your|ur)\b.{0,25}\b(?:budget|max(?:imum)?\s+(?:price|budget|amount)|walk[-\s]?away|upper\s+limit|price\s+limit|spending\s+limit|ceiling)\b|\bhow\s+(?:high|far)\s+(?:will|can|would|are)\s+you\s+(?:go|willing)\b|\bhow\s+much\s+(?:are|can|will|would)\s+you\s+(?:willing\s+to\s+)?(?:pay|spend|go)\b|\bwhat\s+is\s+your\s+(?:limit|range|cap|top\s+price)\b"),
    _r("sens_budget_roman", "sensitive_request", "asks for your budget (Roman Urdu)",
       r"\b(?:aap|apka|aapka|apna|tumhara|tera)\b.{0,15}\b(?:budget|limit|maximum|max)\b|\bkitna\s+(?:budget|paisa|paise|pay\s+kar)\b|\bkitne\s+tak\s+(?:jaa|ja)\s+sakte\b"),
    _r("sens_address", "sensitive_request", "asks for your address",
       r"\b(?:your|ur)\b.{0,12}\b(?:address|location|home|house|residence)\b|\b(?:send|share|give|provide|confirm|tell)\b.{0,20}\b(?:delivery\s+|shipping\s+|home\s+)?address\b|\bwhere\s+(?:do|are)\s+you\s+(?:live|located|based)\b|\b(?:delivery|shipping|home)\s+address\b|\bpin\s*location\b"),
    _r("sens_address_roman", "sensitive_request", "asks for your address (Roman Urdu)",
       r"\b(?:apna|aap\s+ka|apka|aapka)\s+(?:address|pata)\b|\bpata\s+(?:bhej\w*|bata\w*|share)\b|\baddress\s+(?:bhej\w*|bata\w*|share|do)\b"),
    _r("sens_phone", "sensitive_request", "asks for your phone or messaging number",
       r"\b(?:your|ur)\b.{0,12}\b(?:phone|mobile|cell|whatsapp|contact\s+(?:number|details?))\b|\b(?:send|share|give)\b.{0,15}\b(?:phone|mobile|whatsapp|contact)\s*(?:number|no\.?)?\b"),
    _r("sens_phone_roman", "sensitive_request", "asks for your phone number (Roman Urdu)",
       r"\b(?:apna|apka|aapka)\s+(?:number|mobile|phone|whatsapp)\b|\b(?:number|mobile)\s+(?:bhej\w*|bata\w*|share|do)\b"),
    _r("sens_identity", "sensitive_request", "asks for identity documents",
       r"\b(?:cnic|national\s+id|id\s+card|passport|ssn|social\s+security|date\s+of\s+birth|dob|driving\s+licen[cs]e|tax\s+id|ntn)\b"),
    _r("sens_owner", "sensitive_request", "asks who the buyer or owner is",
       r"\bwho\s+(?:is|are)\s+(?:your|the)\s+(?:owner|buyer|boss|client)\b|\byour\s+(?:owner|boss|client)(?:'?s)?\s+(?:name|number|email|address|phone)\b"),
    _r("sens_off_platform", "sensitive_request", "asks to move the conversation off the platform",
       r"\b(?:contact|message|text|call|reach|ping|dm)\s+me\s+(?:on|at|via|through)\s+(?:whatsapp|telegram|signal|instagram|facebook|messenger|wechat|skype|personal|private)\b|\b(?:move|take|continue)\s+(?:this|the|our)\s*(?:chat|conversation|deal|discussion)?\s+(?:to|off|over\s+to|on)\s+(?:whatsapp|telegram|signal|instagram|facebook|messenger|wechat|skype|email|call|phone|another|a\s+different|private|personal)\b|\boutside\s+(?:of\s+)?(?:this\s+)?(?:platform|chat|dealdesk)\b|\bdirect(?:ly)?\s+(?:deal|payment)\b|\bpersonal\s+(?:number|email|account)\b"),
    # ---------------- payment risk (more than the Limit Checker's word list)
    _r("pay_account_details", "payment_risk", "shares or asks for bank or wallet details",
       r"\b(?:iban|swift|routing\s+number|account\s+(?:number|no\.?|title)|sort\s+code|ifsc|wallet\s+address)\b|\b0x[a-f0-9]{20,}\b"),
    _r("pay_send_first", "payment_risk", "asks you to pay first",
       r"\bsend\s+(?:the\s+)?(?:money|payment|funds|cash|amount)\b.{0,25}\b(?:first|before|now|today|to\s+this|to\s+my)\b|\bpay\s+(?:me|us)?\s*(?:first|before\s+(?:delivery|shipping|dispatch))\b|\bpay\s+(?:me|us)\s+(?:now|today)\b"),
    _r("pay_fees", "payment_risk", "asks for a fee before delivery",
       r"\b(?:token|booking|registration|processing|shipping|customs|clearance|handling|insurance|verification|release|activation)\s+(?:fee|fees|charge|charges|amount|payment|money)\b|\brefundable\s+(?:fee|deposit)\b"),
    _r("pay_partial_first", "payment_risk", "asks for part of the payment up front",
       r"\b(?:pay|send|transfer)\b.{0,20}\b(?:half|partial|\d{1,2}\s*(?:%|percent))(?!\w).{0,15}\b(?:first|now|upfront|up-front|advance|before)\b"),
    _r("pay_wallets", "payment_risk", "asks for payment through a wallet or app",
       r"\b(?:sadapay|nayapay|raast|paypal|cash\s?app|payoneer|upi|paytm|gpay|google\s+pay|apple\s+pay|wise\s+transfer)\b"),
    _r("pay_roman", "payment_risk", "asks for payment first (Roman Urdu)",
       r"\b(?:pehle|pehly|pahle)\s+(?:pay|payment|paise|paisay|rupay|amount)\b|\bpaise\s+(?:pehle|pehly|bhej\w*)\b|\badvance\s+(?:do|dena|bhej\w*)\b"),
    _r("pay_credentials", "payment_risk", "asks for card, one-time code or login details",
       r"\b(?:otp|one[-\s]?time\s+(?:password|code|pin)|verification\s+code|cvv|cvc|card\s+number|pin\s+code|password|2fa|security\s+code|log\s*in\s+details|username)\b"),
    # ---------------- links, files and downloads
    _r("link_url", "suspicious_link", "contains a web link", r"\bhttps?://\S+|\bwww\.\S+", ("nolink",)),
    _r("link_domain", "suspicious_link", "contains a web address",
       r"\b[a-z0-9-]+\.(?:com|net|org|io|co|xyz|top|click|link|info|biz|shop|store|ru|cn|tk|ml|ga|cf|gq|pk|app|site|online)\b/\S*", ("nolink",)),
    _r("link_spelled_out", "suspicious_link", "contains a web address written out in words",
       r"\b[a-z0-9-]{3,}\s+(?:dot|d0t)\s+(?:com|net|org|io|co|xyz|top|click|link|info|biz|shop|store|pk|app|site|online)\b", ("nolink",)),
    _r("link_shortener", "suspicious_link", "contains a shortened link",
       r"\b(?:bit\.ly|tinyurl|t\.co|goo\.gl|ow\.ly|is\.gd|cutt\.ly|rb\.gy|shorturl|wa\.me|t\.me)\b", ("nolink",)),
    _r("link_click", "suspicious_link", "asks you to click, scan or install something",
       r"\bclick\s+(?:here|the\s+link|this\s+link|below|on\s+the\s+link)\b|\b(?:scan|use)\s+(?:the\s+|this\s+)?qr\b|\b(?:download|install)\s+(?:this|the|our|my)\s+(?:app|apk|file|software|attachment)\b|\bopen\s+(?:the\s+)?attachment\b|\blog\s*in\s+(?:here|to\s+verify|to\s+confirm)\b"),
    _r("link_file", "suspicious_link", "mentions a risky file type",
       r"\.(?:apk|exe|scr|bat|msi|zip|rar|js|vbs|dmg)\b"),
]

# Key phrases checked on the letters-only view, to catch "i.g.n.o.r.e y-o-u-r r.u.l.e.s"
_JOINED = [
    ("inj_joined_ignore", re.compile(r"(?:ignore|disregard|forget|override|bypass)(?:all|any|your|the|my|previous|prior|above|earlier|these|those)*(?:rules?|instructions?|prompts?|guidelines?|programming)")),
    ("inj_joined_role", re.compile(r"youarenow(?:a|an|the|my|dan|unrestricted|acting)")),
    ("inj_joined_prompt", re.compile(r"(?:your|the)?systemprompt|developermode|jailbreak")),
]  # fmt: skip


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    verdict: Verdict
    reason: str


def scan(text: str) -> tuple[list[RuleHit], Cleaned]:
    """Runs every rule over the cleaned text. Returns the hits and the cleaned views."""
    c = clean(text)
    hits: dict[str, RuleHit] = {}

    no_email = _EMAIL.sub(" ", c.plain)  # an email address is not a web link
    views = {"plain": c.plain, "leet": c.leet, "spaced": c.spaced, "raw": c.raw, "nolink": no_email}

    for rule in RULES:
        for view in rule.views:
            if rule.pattern.search(views[view]):
                hits[rule.id] = RuleHit(rule.id, rule.verdict, rule.reason)
                break

    for rid, pat in _JOINED:
        if pat.search(c.joined):
            hits[rid] = RuleHit(rid, "injection", "hides an instruction to the AI inside spaced-out letters")

    for term in find_payment_commitments(c.plain):
        hits.setdefault("pay_terms", RuleHit("pay_terms", "payment_risk", f"asks for a payment method that is not cash on delivery ('{term}')"))

    return list(hits.values()), c


def strongest(hits: list[RuleHit]) -> Verdict:
    if not hits:
        return "ok"
    return max((h.verdict for h in hits), key=lambda v: SEVERITY[v])
