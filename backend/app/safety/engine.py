import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SafetyState(StrEnum):
    NORMAL = "NORMAL"
    NEEDS_SUPPORT = "NEEDS_SUPPORT"
    POTENTIAL_CRISIS = "POTENTIAL_CRISIS"
    IMMEDIATE_DANGER = "IMMEDIATE_DANGER"


class SafetyReasonCode(StrEnum):
    NO_INDICATOR = "NO_INDICATOR"
    GENERAL_DISTRESS = "GENERAL_DISTRESS"
    AMBIGUOUS_EXPRESSION = "AMBIGUOUS_EXPRESSION"
    SELF_HARM_IDEATION = "SELF_HARM_IDEATION"
    IMMEDIATE_INTENT = "IMMEDIATE_INTENT"
    CONTEXTUAL_NEGATION = "CONTEXTUAL_NEGATION"


class SafetyConfirmationState(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    CONFIRMATION_PENDING = "CONFIRMATION_PENDING"
    CALLER_REPORTS_SAFE = "CALLER_REPORTS_SAFE"
    CALLER_DECLINES = "CALLER_DECLINES"


class SafetyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: SafetyState
    reason_code: SafetyReasonCode


_NEGATED_CONCERN_PHRASES = (
    "tidak ingin bunuh diri",
    "tidak mau bunuh diri",
    "tidak akan bunuh diri",
    "tidak ingin melukai diri",
    "tidak akan melukai diri",
    "tidak ingin menyakiti diri",
    "tidak ingin mati",
    "not suicidal",
    "not thinking about suicide",
    "don't want to hurt myself",
    "do not want to hurt myself",
    "not going to hurt myself",
    "don't want to die",
)
_IMMEDIATE_PHRASES = (
    "akan bunuh diri sekarang",
    "mau bunuh diri sekarang",
    "akan mengakhiri hidup sekarang",
    "sedang melukai diri",
    "sedang menyakiti diri",
    "sudah melukai diri",
    "sudah minum racun",
    "i am going to kill myself now",
    "i'm going to kill myself now",
    "i am hurting myself right now",
    "i have taken poison",
)
_NEGATED_IMMEDIATE_PHRASES = (
    "tidak akan bunuh diri sekarang",
    "tidak akan melukai diri sekarang",
    "i am not going to kill myself now",
    "i'm not going to kill myself now",
    "i am not hurting myself right now",
    "i'm not hurting myself right now",
)
_CRISIS_PHRASES = (
    "bunuh diri",
    "bunuh diriku",
    "suicidal",
    "ingin mati",
    "mengakhiri hidup",
    "melukai diri",
    "menyakiti diri",
    "tidak ingin hidup",
    "suicide",
    "kill myself",
    "hurt myself",
    "self-harm",
    "end my life",
    "want to die",
    "wanna die",
    "i want to be dead",
    "might hurt myself",
    "might kill myself",
    "mungkin melukai diri",
    "mungkin menyakiti diri",
)
_AMBIGUOUS_PHRASES = (
    "capek hidup",
    "lelah hidup",
    "ingin menghilang",
    "ingin hilang saja",
    "tidak kuat lagi",
    "lebih baik aku tidak ada",
    "wish i could disappear",
    "can't go on",
    "cannot go on",
    "i don't want to be here",
    "but i might",
    "but maybe",
    "tapi mungkin",
)
_DISTRESS_PHRASES = (
    "cemas",
    "sedih",
    "takut",
    "panik",
    "tertekan",
    "kewalahan",
    "kesepian",
    "anxious",
    "sad",
    "afraid",
    "panicking",
    "overwhelmed",
    "lonely",
)
_SAFE_CONFIRMATION_PHRASES = (
    "saya aman",
    "saya tidak dalam bahaya",
    "saya baik-baik saja",
    "i am safe",
    "i'm safe",
    "i am not in danger",
    "i feel safe",
)
_EXPLICIT_END_PHRASES = (
    "akhiri panggilan",
    "akhiri saja",
    "akhiri panggilan",
    "akhiri telepon",
    "tutup panggilan",
    "tutup telepon",
    "sudahi panggilan",
    "sudahi telepon",
    "putuskan panggilan",
    "saya mau tutup",
    "saya mau mengakhiri panggilan",
    "saya ingin mengakhiri panggilan",
    "saya ingin selesai",
    "saya mau selesai",
    "aku ingin selesai",
    "aku mau selesai",
    "cukup sampai sini",
    "berhenti saja",
    "stop panggilan",
    "sudahi sekarang",
    "saya ingin berhenti sekarang",
    "saya ingin tutup telepon",
    "sampai di sini saja",
    "end the call",
    "hang up",
    "end this call",
    "i still want to end the call",
    "i want to hang up now",
)
_NEGATED_END_PHRASES = (
    "jangan akhiri panggilan",
    "jangan akhiri telepon",
    "jangan tutup telepon",
    "tidak perlu mengakhiri panggilan",
    "tidak ingin mengakhiri panggilan",
    "don't end the call",
    "do not end the call",
    "don't hang up",
    "do not hang up",
)


def caller_reports_safe(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    return any(phrase in normalized for phrase in _SAFE_CONFIRMATION_PHRASES)


_END_ACTION = r"(?:mengakhiri|akhiri|menutup|tutup|menyudahi|sudahi|menghentikan|hentikan|berhenti|stop|end|hang\s+up)"
_NEGATED_END_REQUEST = re.compile(
    rf"\b(?:jangan|tidak|tak|belum|nggak|gak|enggak|ga|don't|do\s+not|not|never)\b"
    rf"(?:\s+\w+){{0,4}}\s+{_END_ACTION}\b"
)
_CONVERSATION_END_REQUEST = re.compile(
    r"(?:^|[.!?,;]\s*|\b(?:tolong|silakan)\s+|"
    r"\b(?:saya|aku)\s+(?:ingin|mau|minta|pengen)\s+(?:untuk\s+)?|"
    r"\b(?:bisa|boleh)(?:kah)?\s+(?:kita|saya)\s+)"
    rf"{_END_ACTION}\s+(?:(?:saja|dulu|aja|sekarang)\s+)?"
    r"(?:panggilan|telepon|percakapan|obrolan|sesi)\b"
)
_ENGLISH_CONVERSATION_END_REQUEST = re.compile(
    r"(?:^|\bplease\s+|\bi\s+(?:want|would\s+like)\s+to\s+)"
    r"(?:end|stop|finish)\s+(?:the|this|our)\s+(?:call|conversation|chat|session)\b"
)


def caller_explicitly_requests_end(text: str) -> bool:
    normalized = " ".join(text.casefold().replace("’", "'").split())
    if (
        any(phrase in normalized for phrase in _NEGATED_END_PHRASES)
        or _NEGATED_END_REQUEST.search(normalized)
    ):
        return False
    return bool(
        any(phrase in normalized for phrase in _EXPLICIT_END_PHRASES)
        or _CONVERSATION_END_REQUEST.search(normalized)
        or _ENGLISH_CONVERSATION_END_REQUEST.search(normalized)
        or re.fullmatch(r"(?:tolong\s+)?(?:akhiri|sudahi)(?:\s+(?:saja|sekarang))?[.!?]*", normalized)
    )


def advance_confirmation_state(
    state: SafetyConfirmationState,
    *,
    confirmation_turn: int | None,
    current_turn: int,
    text: str,
    evaluation: SafetyEvaluation,
) -> SafetyConfirmationState:
    if (
        state != SafetyConfirmationState.CONFIRMATION_PENDING
        or confirmation_turn is None
        or current_turn <= confirmation_turn
    ):
        return state
    if caller_explicitly_requests_end(text):
        return SafetyConfirmationState.CALLER_DECLINES
    if (
        caller_reports_safe(text)
        and evaluation.state
        not in {SafetyState.POTENTIAL_CRISIS, SafetyState.IMMEDIATE_DANGER}
    ):
        return SafetyConfirmationState.CALLER_REPORTS_SAFE
    return state


class SafetyEngine:
    """Small, deterministic operational safety gate; these categories are not diagnoses."""

    def evaluate(self, text: str) -> SafetyEvaluation:
        normalized = " ".join(text.casefold().split())
        for phrase in _NEGATED_IMMEDIATE_PHRASES:
            normalized = normalized.replace(phrase, " ")
        negated = any(phrase in normalized for phrase in _NEGATED_CONCERN_PHRASES)
        remaining = normalized
        for phrase in _NEGATED_CONCERN_PHRASES:
            remaining = remaining.replace(phrase, " ")
        if any(phrase in remaining for phrase in _IMMEDIATE_PHRASES):
            return SafetyEvaluation(
                state=SafetyState.IMMEDIATE_DANGER,
                reason_code=SafetyReasonCode.IMMEDIATE_INTENT,
            )
        if any(phrase in remaining for phrase in _CRISIS_PHRASES):
            return SafetyEvaluation(
                state=SafetyState.POTENTIAL_CRISIS,
                reason_code=SafetyReasonCode.SELF_HARM_IDEATION,
            )
        if negated:
            if any(phrase in remaining for phrase in _DISTRESS_PHRASES):
                return SafetyEvaluation(
                    state=SafetyState.NEEDS_SUPPORT,
                    reason_code=SafetyReasonCode.GENERAL_DISTRESS,
                )
            return SafetyEvaluation(
                state=SafetyState.NORMAL,
                reason_code=SafetyReasonCode.CONTEXTUAL_NEGATION,
            )
        if any(phrase in remaining for phrase in _AMBIGUOUS_PHRASES):
            return SafetyEvaluation(
                state=SafetyState.NEEDS_SUPPORT,
                reason_code=SafetyReasonCode.AMBIGUOUS_EXPRESSION,
            )
        if any(phrase in remaining for phrase in _DISTRESS_PHRASES):
            return SafetyEvaluation(
                state=SafetyState.NEEDS_SUPPORT,
                reason_code=SafetyReasonCode.GENERAL_DISTRESS,
            )
        return SafetyEvaluation(
            state=SafetyState.NORMAL,
            reason_code=SafetyReasonCode.NO_INDICATOR,
        )


class SafetyStateTracker:
    """Keeps elevated safety handling active across short follow-up turns."""

    def __init__(self, clear_after_turns: int = 3):
        self.state = SafetyState.NORMAL
        self._clear_after_turns = clear_after_turns
        self._remaining_turns = 0

    def update(self, evaluation: SafetyEvaluation) -> SafetyState:
        if evaluation.state in {SafetyState.POTENTIAL_CRISIS, SafetyState.IMMEDIATE_DANGER}:
            severity = {
                SafetyState.POTENTIAL_CRISIS: 1,
                SafetyState.IMMEDIATE_DANGER: 2,
            }
            if (
                self.state not in severity
                or severity[evaluation.state] >= severity[self.state]
            ):
                self.state = evaluation.state
            self._remaining_turns = self._clear_after_turns
        elif evaluation.reason_code == SafetyReasonCode.CONTEXTUAL_NEGATION:
            self.state = SafetyState.NEEDS_SUPPORT
            self._remaining_turns = 1
        elif self.state in {SafetyState.POTENTIAL_CRISIS, SafetyState.IMMEDIATE_DANGER}:
            self._remaining_turns -= 1
            if self._remaining_turns <= 0:
                self.state = SafetyState.NEEDS_SUPPORT
        elif evaluation.state == SafetyState.NORMAL and self.state == SafetyState.NEEDS_SUPPORT:
            self.state = SafetyState.NORMAL
        else:
            self.state = evaluation.state
        return self.state

    def record_user_safe_report(self) -> SafetyState:
        self.state = SafetyState.NEEDS_SUPPORT
        self._remaining_turns = 0
        return self.state
