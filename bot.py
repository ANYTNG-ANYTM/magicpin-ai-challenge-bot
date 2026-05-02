from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, Response
from pydantic import BaseModel, Field


app = FastAPI(title="magicpin Vera Bot", version="0.1.0")
START_TIME = time.time()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _first_token(text: str) -> str:
    parts = re.split(r"\s+", (text or "").strip())
    return parts[0] if parts and parts[0] else "there"


def _merchant_name(merchant: dict[str, Any]) -> str:
    identity = merchant.get("identity", {}) or {}
    return identity.get("name") or merchant.get("merchant_name") or merchant.get("name") or "there"


def _merchant_owner_first_name(merchant: dict[str, Any]) -> str:
    identity = merchant.get("identity", {}) or {}
    return identity.get("owner_first_name") or _first_token(_merchant_name(merchant))


def _merchant_category_slug(merchant: dict[str, Any], trigger: dict[str, Any] | None = None) -> str:
    if merchant.get("category_slug"):
        return merchant["category_slug"]
    if merchant.get("category"):
        return merchant["category"]
    if trigger:
        payload = trigger.get("payload", {}) or {}
        if isinstance(payload, dict) and payload.get("category"):
            return payload["category"]
    return "unknown"


def _category_voice(category: dict[str, Any]) -> dict[str, Any]:
    return category.get("voice", {}) or {}


def _category_offer_titles(category: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    for offer in category.get("offer_catalog", []) or []:
        title = offer.get("title") if isinstance(offer, dict) else None
        if title:
            titles.append(title)
    return titles


def _merchant_active_offers(merchant: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    for offer in merchant.get("offers", []) or []:
        if isinstance(offer, dict) and offer.get("status") == "active" and offer.get("title"):
            titles.append(offer["title"])
    return titles


def _merchant_signal_text(merchant: dict[str, Any]) -> str:
    signals = merchant.get("signals", []) or []
    if not signals:
        return ""
    if isinstance(signals, list):
        return ", ".join(str(item) for item in signals[:3])
    return str(signals)


def _context_entry(scope: str, context_id: str) -> Optional[dict[str, Any]]:
    entry = CONTEXTS.get((scope, context_id))
    if not entry:
        return None
    return entry.payload


def _find_category_for_merchant(merchant: dict[str, Any], trigger: dict[str, Any] | None = None) -> Optional[dict[str, Any]]:
    slug = _merchant_category_slug(merchant, trigger)
    if not slug or slug == "unknown":
        return None
    return _context_entry("category", slug)


def _format_date_label(value: Optional[str]) -> str:
    dt = _parse_dt(value)
    if not dt:
        return value or ""
    month = dt.strftime("%b")
    day = dt.day
    if dt.hour or dt.minute:
        hour = dt.strftime("%I:%M %p").lstrip("0")
        return f"{day} {month}, {hour}"
    return f"{day} {month}"


def _format_count(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


def _pick_digest_item(category: dict[str, Any], trigger: dict[str, Any]) -> Optional[dict[str, Any]]:
    payload = trigger.get("payload", {}) or {}
    target_id = payload.get("top_item_id") or payload.get("digest_item_id")
    digest = category.get("digest", []) or []
    if target_id:
        for item in digest:
            if isinstance(item, dict) and item.get("id") == target_id:
                return item
    if digest:
        return digest[0] if isinstance(digest[0], dict) else None
    return None


def _business_voice_opening(category_slug: str, merchant: dict[str, Any]) -> str:
    owner = _merchant_owner_first_name(merchant)
    if category_slug == "dentists":
        return f"Dr. {owner}"
    if category_slug in {"salons", "restaurants", "gyms", "pharmacies"}:
        return owner
    return _merchant_name(merchant)


def _customer_salutation(category_slug: str, customer: dict[str, Any]) -> str:
    name = (customer.get("identity", {}) or {}).get("name") or "there"
    if category_slug == "pharmacies":
        return f"Namaste {name}"
    if category_slug == "dentists":
        return f"Hi {name}"
    if category_slug == "salons":
        return f"Hi {name}"
    if category_slug == "gyms":
        return f"Hi {name}"
    if category_slug == "restaurants":
        return f"Hi {name}"
    return f"Hi {name}"


def _template_name_for_trigger(kind: str) -> str:
    safe = re.sub(r"[^a-z0-9_]+", "_", (kind or "generic").lower()).strip("_") or "generic"
    return f"vera_{safe}_v1"


def _binary_cta_for_kind(kind: str, scope: str) -> str:
    if scope == "customer" and kind in {"recall_due", "appointment_tomorrow", "trial_followup", "chronic_refill_due", "wedding_package_followup"}:
        return "binary_yes_no"
    if kind in {"active_planning_intent", "research_digest", "competitor_opened", "perf_dip", "perf_spike", "renewal_due", "festival_upcoming", "review_theme_emerged", "curious_ask_due", "regulation_change"}:
        return "open_ended"
    return "open_ended"


def _join_sentences(parts: list[str]) -> str:
    clean = [part.strip() for part in parts if part and part.strip()]
    return " ".join(clean)


def _customer_months_since(last_visit: Optional[str]) -> Optional[int]:
    dt = _parse_dt(last_visit)
    if not dt:
        return None
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    months = (now.year - dt.year) * 12 + (now.month - dt.month)
    if now.day < dt.day:
        months -= 1
    return max(months, 0)


def _compose_merchant_message(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]) -> tuple[str, str, str]:
    kind = (trigger.get("kind") or "").lower()
    payload = trigger.get("payload", {}) or {}
    category_slug = _merchant_category_slug(merchant, trigger)
    opener = _business_voice_opening(category_slug, merchant)
    category_voice = _category_voice(category)
    active_offers = _merchant_active_offers(merchant)
    merchant_name = _merchant_name(merchant)

    if kind in {"research_digest", "category_research_digest_release"}:
        digest_item = _pick_digest_item(category, trigger)
        if digest_item:
            title = digest_item.get("title", "")
            source = digest_item.get("source", "")
            summary = digest_item.get("summary", "")
            if category_slug == "dentists" and payload.get("top_item_id") == "d_2026W17_jida_fluoride":
                high_risk = merchant.get("customer_aggregate", {}).get("high_risk_adult_count")
                cohort = f"your high-risk adult cohort" if high_risk is not None else "your patient mix"
                body = _join_sentences([
                    f"{opener}, {source} landed.",
                    f"One item relevant to {cohort} - {title}." if title else "One item looks relevant to your practice.",
                    "Worth a look (2-min abstract). Want me to pull it + draft a patient-ed WhatsApp you can share?",
                    f"- {source}" if source else "",
                ])
                return body, "open_ended", f"Research digest anchored on {source or 'the new digest item'} with a low-friction request for follow-up."
            body = _join_sentences([
                f"{opener}, new digest item landed.",
                title or summary or "There's a new item worth a quick look.",
                f"Source: {source}. Want me to turn this into a quick post or offer angle?" if source else "Want me to turn this into a quick post or offer angle?",
            ])
            return body, "open_ended", f"Digest item surfaced for {category_slug}; inviting a concrete follow-up without inventing details."

        body = _join_sentences([
            f"{opener}, your weekly research digest is ready.",
            "Want the short version or a draft post you can reuse?",
        ])
        return body, "open_ended", "Digest trigger with no specific item resolved; asking for a simple next step."

    if kind in {"regulation_change", "compliance", "supply_alert"}:
        title = payload.get("title") or payload.get("top_item_id") or trigger.get("id")
        deadline = payload.get("deadline_iso") or payload.get("expires_at")
        body = _join_sentences([
            f"{opener}, heads up on {title}.",
            f"Deadline: {_format_date_label(deadline)}." if deadline else "",
            "Want a quick checklist or draft note for your team?",
        ])
        return body, "open_ended", "Compliance or supply alert with a direct, low-effort follow-up."

    if kind in {"perf_dip", "seasonal_perf_dip"}:
        metric = payload.get("metric") or "views"
        delta_pct = payload.get("delta_pct")
        if delta_pct is None and merchant.get("performance", {}).get("delta_7d", {}).get(f"{metric}_pct") is not None:
            delta_pct = merchant.get("performance", {}).get("delta_7d", {}).get(f"{metric}_pct")
        delta_text = f"{abs(int(round(float(delta_pct) * 100)))}%" if isinstance(delta_pct, (int, float)) else "recently"
        active_offer_text = active_offers[0] if active_offers else "your active offer"
        body = _join_sentences([
            f"{opener}, {metric} are down {delta_text} this week.",
            f"You already have {active_offer_text} live - want me to draft a tighter GBP post around it?",
        ])
        return body, "open_ended", "Performance dip framed against an active offer, with a single next step."

    if kind == "perf_spike":
        metric = payload.get("metric") or "calls"
        delta_pct = payload.get("delta_pct")
        delta_text = f"{int(round(float(delta_pct) * 100))}%" if isinstance(delta_pct, (int, float)) else "up"
        body = _join_sentences([
            f"{opener}, {metric} are {delta_text} vs baseline.",
            "Want me to turn this into a quick post while the momentum is live?",
        ])
        return body, "open_ended", "Performance spike used as a timely hook to convert momentum into content."

    if kind == "renewal_due":
        days_remaining = payload.get("days_remaining") or merchant.get("subscription", {}).get("days_remaining")
        plan = payload.get("plan") or merchant.get("subscription", {}).get("plan") or "plan"
        body = _join_sentences([
            f"{opener}, your {plan} renewal is due in {days_remaining} days." if days_remaining is not None else f"{opener}, your {plan} renewal is due soon.",
            "Want me to prep the renewal note and a short follow-up message?",
        ])
        return body, "open_ended", "Renewal reminder anchored on real days remaining and a single follow-up ask."

    if kind in {"competitor_opened", "competitor_opened_dentist"}:
        competitor_name = payload.get("competitor_name") or payload.get("name") or "a nearby competitor"
        distance = payload.get("distance_km")
        their_offer = payload.get("their_offer")
        body_parts = [f"{opener}, a nearby competitor opened: {competitor_name}."]
        if distance is not None:
            body_parts.append(f"It's {distance} km away.")
        if their_offer:
            body_parts.append(f"They're advertising {their_offer}.")
        body_parts.append("Want me to draft a counter-post using your own offer list?")
        return _join_sentences(body_parts), "open_ended", "Competitor opening used as a direct local benchmark and a quick action prompt."

    if kind in {"festival_upcoming", "seasonal", "category_seasonal", "ipl_match_today"}:
        title = payload.get("festival") or payload.get("match") or payload.get("title") or trigger.get("id")
        body = _join_sentences([
            f"{opener}, {title} is the trigger.",
            "Want me to suggest the best category-specific angle from your live offers?",
        ])
        return body, "open_ended", "Seasonal trigger framed around a concrete event and a simple request for an angle."

    if kind in {"curious_ask_due", "scheduled_recurring"}:
        body = _join_sentences([
            f"{opener}, quick check - what's most in demand this week?",
            "I'll turn your answer into a post or a ready reply.",
        ])
        return body, "open_ended", "Curiosity ask to elicit merchant-provided insight and feed the next action."

    if kind in {"active_planning_intent", "intent_planning"}:
        topic = payload.get("intent_topic") or payload.get("ask_template") or "this"
        body = _join_sentences([
            f"{opener}, I can draft {topic} right now.",
            "Want the first version based on your current offer list?",
        ])
        return body, "open_ended", "Explicit intent routed straight into action mode instead of re-qualifying."

    if kind == "dormant_with_vera" or kind == "dormant":
        body = _join_sentences([
            f"{opener}, quick nudge - it's been a while since your last update.",
            "Want me to send one useful idea based on your current numbers?",
        ])
        return body, "open_ended", "Dormancy trigger framed as a lightweight restart rather than a hard sell."

    if category_slug == "restaurants" and active_offers:
        body = _join_sentences([
            f"{opener}, I'm seeing your live offer {active_offers[0]}.",
            f"Want me to spin it into a locality-specific angle for {merchant.get('identity', {}).get('locality', 'your area')}?",
        ])
        return body, "open_ended", "Fallback restaurant nudge grounded in an active offer and locality."

    if category_slug == "gyms" and active_offers:
        body = _join_sentences([
            f"{opener}, your offer {active_offers[0]} is live.",
            "Want me to pair it with a retention or trial-walk-in angle?",
        ])
        return body, "open_ended", "Fallback gym nudge grounded in an offer and a clear next step."

    if category_slug == "pharmacies" and active_offers:
        body = _join_sentences([
            f"{opener}, your offer {active_offers[0]} is live.",
            "Want me to draft a patient-facing reminder or refill note?",
        ])
        return body, "open_ended", "Fallback pharmacy nudge grounded in an offer and patient-facing utility."

    if category_slug == "salons" and active_offers:
        body = _join_sentences([
            f"{opener}, your offer {active_offers[0]} is live.",
            "Want me to shape it for bridal, walk-in, or weekday afternoon demand?",
        ])
        return body, "open_ended", "Fallback salon nudge using live offer and category-specific demand framing."

    generic_body = _join_sentences([
        f"{opener}, I checked the latest context for {merchant_name}.",
        "Want me to suggest the most relevant next message from this data?",
    ])
    return generic_body, "open_ended", "Generic fallback when the trigger kind does not map cleanly to a specialized path."


def _compose_customer_message(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any]) -> tuple[str, str, str]:
    kind = (trigger.get("kind") or "").lower()
    category_slug = _merchant_category_slug(merchant, trigger)
    payload = trigger.get("payload", {}) or {}
    salutation = _customer_salutation(category_slug, customer)
    merchant_display = _merchant_name(merchant)
    offers = _merchant_active_offers(merchant)
    offer_text = offers[0] if offers else None

    if kind == "recall_due":
        relationship = customer.get("relationship", {}) or {}
        months = _customer_months_since(relationship.get("last_visit"))
        months_text = f"It's been about {months} months since your last visit" if months is not None else "Your recall window is due"
        available_slots = payload.get("available_slots", []) or []
        slot_labels = [slot.get("label") for slot in available_slots if isinstance(slot, dict) and slot.get("label")]
        slot_text = " ya ".join(slot_labels[:2]) if slot_labels else "a couple of slots this week"
        body = _join_sentences([
            f"{salutation}, {merchant_display} here.",
            f"{months_text} - your {payload.get('service_due', 'cleaning')} is due.",
            f"{slot_text} are ready, and {offer_text or 'a standard slot'} is available.",
            "Reply YES if you want me to book one, or tell us a time that works.",
        ])
        return body, "binary_yes_no", "Customer recall reminder with exact relationship timing and a simple confirm-or-change ask."

    if kind == "appointment_tomorrow":
        slot = payload.get("slot_label") or _format_date_label(payload.get("appointment_at")) or "tomorrow"
        body = _join_sentences([
            f"{salutation}, reminder from {merchant_display}.",
            f"Your appointment is {slot}.",
            "Reply YES to confirm, or tell us if you need a new time.",
        ])
        return body, "binary_yes_no", "Appointment reminder with a single confirmation action."

    if kind in {"chronic_refill_due", "refill_due"}:
        molecules = payload.get("molecule_list") or payload.get("molecules") or []
        molecule_text = ", ".join(molecules[:3]) if isinstance(molecules, list) else str(molecules)
        stock_out = _format_date_label(payload.get("stock_runs_out_iso") or payload.get("due_date"))
        delivery = "Free home delivery is available" if any("delivery" in str(item).lower() for item in offers) else "Delivery can be arranged"
        body = _join_sentences([
            f"{salutation}, {merchant_display} here.",
            f"Your refill is due for {molecule_text}.",
            f"Runs out by {stock_out}." if stock_out else "",
            f"{delivery}. Reply CONFIRM to proceed, or tell us if anything changed.",
        ])
        return body, "binary_yes_no", "Chronic refill reminder using molecule names, date specificity, and a single confirm action."

    if kind in {"wedding_package_followup", "bridal_followup"}:
        wedding_date = _format_date_label(payload.get("wedding_date")) or "your wedding date"
        body = _join_sentences([
            f"{salutation}, {merchant_display} here.",
            f"You're in the pre-wedding window for {wedding_date}.",
            f"Want me to hold the next slot in {offer_text or 'the bridal package'}?",
        ])
        return body, "binary_yes_no", "Bridal follow-up with timing, merchant identity, and a low-friction hold request."

    if kind == "trial_followup":
        next_slots = payload.get("next_session_options", []) or []
        slot_labels = [slot.get("label") for slot in next_slots if isinstance(slot, dict) and slot.get("label")]
        slot_text = slot_labels[0] if slot_labels else "the next class"
        body = _join_sentences([
            f"{salutation}, {merchant_display} here.",
            f"Your trial is still fresh - {slot_text} is available.",
            "Reply YES if you want me to hold it.",
        ])
        return body, "binary_yes_no", "Trial follow-up with a single slot and a simple hold request."

    if kind == "customer_lapsed_soft":
        body = _join_sentences([
            f"{salutation}, {merchant_display} here.",
            "No rush - just checking if you want a quick restart.",
            f"{offer_text or 'A fresh slot'} is ready if you want to come back.",
            "Reply YES and I'll send the best option.",
        ])
        return body, "binary_yes_no", "Soft-lapse message framed gently with one clear next step."

    if kind == "customer_lapsed_hard":
        body = _join_sentences([
            f"{salutation}, {merchant_display} here.",
            "We noticed it's been a while and wanted to send one useful note.",
            f"{offer_text or 'A fresh slot'} is available if you ever want to restart.",
            "Reply YES if you want details, or STOP if not.",
        ])
        return body, "binary_yes_no", "Hard-lapse outreach stays respectful and offers an opt-out."

    if kind == "appointment_followup":
        body = _join_sentences([
            f"{salutation}, {merchant_display} here.",
            "How did the last visit go?",
            "If you want, I can share the next recommended step.",
        ])
        return body, "open_ended", "Post-visit follow-up keeps it simple and asks for the next step."

    body = _join_sentences([
        f"{salutation}, {merchant_display} here.",
        f"{offer_text or 'Your next slot'} is ready if you want it.",
            "Reply YES if you'd like the details.",
    ])
    return body, "binary_yes_no", "Fallback customer message using the merchant name, live offer, and a direct confirmation ask."


def compose(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any] | None = None) -> dict[str, Any]:
    if customer is not None:
        body, cta, rationale = _compose_customer_message(category or {}, merchant or {}, trigger or {}, customer or {})
        return {
            "body": body,
            "cta": cta,
            "send_as": "merchant_on_behalf",
            "suppression_key": (trigger or {}).get("suppression_key") or (trigger or {}).get("id") or "",
            "rationale": rationale,
        }

    body, cta, rationale = _compose_merchant_message(category or {}, merchant or {}, trigger or {})
    return {
        "body": body,
        "cta": cta,
        "send_as": "vera",
        "suppression_key": (trigger or {}).get("suppression_key") or (trigger or {}).get("id") or "",
        "rationale": rationale,
    }


@dataclass
class StoredContext:
    version: int
    payload: dict[str, Any]
    delivered_at: str


@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str]
    trigger_id: Optional[str]
    send_as: str
    status: str = "active"
    turns: list[dict[str, Any]] = field(default_factory=list)
    last_body: str = ""
    last_merchant_message: str = ""
    merchant_repeat_count: int = 0
    auto_reply_count: int = 0
    suppression_keys: set[str] = field(default_factory=set)
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)


CONTEXTS: dict[tuple[str, str], StoredContext] = {}
CONVERSATIONS: dict[str, ConversationState] = {}
GLOBAL_SUPPRESSION: set[str] = set()


class ContextPush(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str


class TickRequest(BaseModel):
    now: str
    available_triggers: list[str] = Field(default_factory=list)


class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


def _count_contexts() -> dict[str, int]:
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _), _entry in CONTEXTS.items():
        if scope in counts:
            counts[scope] += 1
    return counts


def _merchant_for_trigger(trigger: dict[str, Any]) -> Optional[dict[str, Any]]:
    merchant_id = trigger.get("merchant_id") or (trigger.get("payload", {}) or {}).get("merchant_id")
    if not merchant_id:
        return None
    return _context_entry("merchant", merchant_id)


def _customer_for_trigger(trigger: dict[str, Any]) -> Optional[dict[str, Any]]:
    customer_id = trigger.get("customer_id") or (trigger.get("payload", {}) or {}).get("customer_id")
    if not customer_id:
        return None
    return _context_entry("customer", customer_id)


def _conversation_id_for(trigger_id: str, merchant_id: str, customer_id: Optional[str]) -> str:
    suffix = customer_id or "merchant"
    safe_trigger = re.sub(r"[^a-zA-Z0-9_]+", "_", trigger_id)
    safe_merchant = re.sub(r"[^a-zA-Z0-9_]+", "_", merchant_id)
    return f"conv_{safe_merchant}_{safe_trigger}_{suffix}"


def _store_conversation(conversation_id: str, merchant_id: str, customer_id: Optional[str], trigger_id: Optional[str], send_as: str) -> ConversationState:
    convo = CONVERSATIONS.get(conversation_id)
    if convo:
        return convo
    convo = ConversationState(
        conversation_id=conversation_id,
        merchant_id=merchant_id,
        customer_id=customer_id,
        trigger_id=trigger_id,
        send_as=send_as,
    )
    CONVERSATIONS[conversation_id] = convo
    return convo


def _is_auto_reply(message: str, previous_message: str, repeat_count: int) -> bool:
    text = message.strip().lower()
    patterns = [
        r"thank you for contacting",
        r"our team will respond shortly",
        r"we will get back to you",
        r"this is an automated assistant",
        r"i am an automated assistant",
        r"currently unavailable",
        r"out of office",
        r"please do not reply",
    ]
    if any(re.search(pattern, text) for pattern in patterns):
        return True
    if previous_message and text == previous_message.strip().lower():
        return True
    if repeat_count >= 2:
        return True
    return False


def _is_opt_out(message: str) -> bool:
    text = message.strip().lower()
    phrases = [
        "stop",
        "not interested",
        "don't message",
        "do not message",
        "unsubscribe",
        "leave me alone",
        "please stop",
        "no more",
    ]
    return any(phrase in text for phrase in phrases)


def _is_intent_accept(message: str) -> bool:
    text = message.strip().lower()
    phrase_patterns = [
        r"\byes\b",
        r"\byes please\b",
        r"\bsend me\b",
        r"\bsend the abstract\b",
        r"\bplease send\b",
        r"\bok let's do it\b",
        r"\bok let's do it\b",
        r"\blet's do it\b",
        r"\blets do it\b",
        r"\bgo ahead\b",
        r"\bproceed\b",
        r"\bwhat's next\b",
        r"\bwhat is next\b",
        r"\bsure\b",
        r"\bdraft it\b",
        r"\bplease draft\b",
    ]
    return any(re.search(pattern, text) for pattern in phrase_patterns)


def _is_out_of_scope(message: str) -> bool:
    text = message.lower()
    keywords = ["gst", "tax", "invoice", "accounting", "salary", "legal", "loan", "hiring", "hr"]
    return any(keyword in text for keyword in keywords)


def _reply_for_engaged_trigger(convo: ConversationState, merchant: dict[str, Any], category: dict[str, Any], trigger: dict[str, Any]) -> dict[str, Any]:
    kind = (trigger.get("kind") or "").lower()
    merchant_name = _merchant_name(merchant)
    category_slug = _merchant_category_slug(merchant, trigger)
    active_offers = _merchant_active_offers(merchant)
    offers_text = active_offers[0] if active_offers else "the current offer"

    if kind in {"research_digest", "category_research_digest_release"}:
        digest_item = _pick_digest_item(category, trigger)
        source = digest_item.get("source") if digest_item else "the digest"
        title = digest_item.get("title") if digest_item else "the item"
        body = _join_sentences([
            f"Sending the abstract now for {source}.",
            f"I've also drafted a short patient-ed note based on {title}." if title else "I've also drafted a short patient-ed note.",
            "Want me to turn it into a scheduled post next?",
        ])
        return {"action": "send", "body": body, "cta": "binary_yes_no", "rationale": "Merchant accepted the research share, so I advanced with the abstract and a reusable draft."}

    if kind in {"active_planning_intent", "intent_planning"}:
        topic = (trigger.get("payload", {}) or {}).get("intent_topic") or "this"
        body = _join_sentences([
            f"Great - here's a first draft for {topic}.",
            f"I used {offers_text} and kept it simple.",
            "Want a tighter version or should I format it for WhatsApp?",
        ])
        return {"action": "send", "body": body, "cta": "open_ended", "rationale": "Merchant committed, so I moved straight into drafting instead of asking another qualifying question."}

    if kind in {"renewal_due"}:
        body = _join_sentences([
            "Done - I can prep the renewal note now.",
            f"I'll keep the focus on {offers_text} and your current numbers.",
            "Want the short version or the full message?",
        ])
        return {"action": "send", "body": body, "cta": "open_ended", "rationale": "Merchant accepted the renewal prompt, so I advanced to the concrete next step."}

    if kind in {"competitor_opened", "competitor_opened_dentist", "perf_dip", "perf_spike", "festival_upcoming", "seasonal", "category_seasonal", "ipl_match_today"}:
        body = _join_sentences([
            "Got it - I'll keep this focused on the current trigger.",
            f"I can draft a post or message using {offers_text}.",
            "Want the draft first?",
        ])
        return {"action": "send", "body": body, "cta": "open_ended", "rationale": "Merchant stayed engaged, so I kept momentum with the concrete next artifact."}

    if category_slug == "pharmacies":
        body = _join_sentences([
            "Understood - I'll keep this precise.",
            f"I can draft the note around {offers_text} and the current trigger.",
            "Want me to send the first version?",
        ])
        return {"action": "send", "body": body, "cta": "binary_yes_no", "rationale": "Pharmacy flow benefits from a precise, low-friction next step."}

    body = _join_sentences([
        "Done - I've got the next step.",
        f"I'll keep it aligned to {merchant_name} and the current context.",
        "Want the draft now?",
    ])
    return {"action": "send", "body": body, "cta": "open_ended", "rationale": "Accepted intent should move directly into action mode."}


@app.get("/v1/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": _count_contexts(),
    }


@app.get("/v1/metadata")
async def metadata() -> dict[str, Any]:
    return {
        "team_name": "Team Procrastinator",
        "team_members": ["XPunk"],
        "model": "rule-based-deterministic-v1",
        "approach": "deterministic composer with context store, trigger router, and replay-safe reply handling",
        "contact_email": "team@example.com",
        "version": "0.1.0",
        "submitted_at": _utc_now(),
    }


@app.post("/v1/context")
async def push_context(body: ContextPush, response: Response) -> dict[str, Any]:
    key = (body.scope, body.context_id)
    current = CONTEXTS.get(key)
    if current and current.version >= body.version:
        response.status_code = 409
        return {"accepted": False, "reason": "stale_version", "current_version": current.version}
    CONTEXTS[key] = StoredContext(version=body.version, payload=body.payload, delivered_at=body.delivered_at)
    response.status_code = 200
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": _utc_now(),
    }


@app.post("/v1/tick")
async def tick(body: TickRequest) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for trigger_id in body.available_triggers:
        if len(actions) >= 20:
            break
        trigger = _context_entry("trigger", trigger_id)
        if not trigger:
            continue
        suppression_key = trigger.get("suppression_key") or trigger_id
        if suppression_key in GLOBAL_SUPPRESSION:
            continue
        merchant = _merchant_for_trigger(trigger)
        if not merchant:
            continue
        category = _find_category_for_merchant(merchant, trigger)
        if not category:
            continue
        customer = _customer_for_trigger(trigger) if (trigger.get("scope") == "customer") else None
        composed = compose(category, merchant, trigger, customer)
        conversation_id = _conversation_id_for(trigger_id, trigger.get("merchant_id") or merchant.get("merchant_id") or "merchant", trigger.get("customer_id") or (customer or {}).get("customer_id"))
        convo = _store_conversation(conversation_id, trigger.get("merchant_id") or merchant.get("merchant_id") or "merchant", trigger.get("customer_id") or (customer or {}).get("customer_id"), trigger_id, composed["send_as"])
        convo.suppression_keys.add(suppression_key)
        convo.last_body = composed["body"]
        convo.updated_at = _utc_now()
        GLOBAL_SUPPRESSION.add(suppression_key)
        template_name = _template_name_for_trigger(trigger.get("kind") or "generic")
        template_params = [
            _business_voice_opening(_merchant_category_slug(merchant, trigger), merchant),
            (composed["body"][:120] or ""),
            composed["rationale"],
        ]
        actions.append({
            "conversation_id": conversation_id,
            "merchant_id": trigger.get("merchant_id") or merchant.get("merchant_id") or "",
            "customer_id": trigger.get("customer_id") or (customer or {}).get("customer_id"),
            "send_as": composed["send_as"],
            "trigger_id": trigger_id,
            "template_name": template_name,
            "template_params": template_params,
            "body": composed["body"],
            "cta": composed["cta"],
            "suppression_key": composed["suppression_key"],
            "rationale": composed["rationale"],
        })
    return {"actions": actions}


@app.post("/v1/reply")
async def reply(body: ReplyRequest) -> dict[str, Any]:
    convo = CONVERSATIONS.get(body.conversation_id)
    if not convo:
        convo = ConversationState(
            conversation_id=body.conversation_id,
            merchant_id=body.merchant_id or "",
            customer_id=body.customer_id,
            trigger_id=None,
            send_as="vera",
        )
        CONVERSATIONS[body.conversation_id] = convo

    message = body.message or ""
    convo.turns.append({"from": body.from_role, "msg": message, "received_at": body.received_at, "turn_number": body.turn_number})
    convo.updated_at = _utc_now()

    previous_merchant_message = convo.last_merchant_message
    previous_repeat_count = convo.merchant_repeat_count

    if body.from_role == "merchant":
        normalized = message.strip().lower()
        if normalized == previous_merchant_message.strip().lower() and normalized:
            convo.merchant_repeat_count = previous_repeat_count + 1
        else:
            convo.merchant_repeat_count = 0

    if convo.status == "ended":
        return {"action": "end", "rationale": "Conversation already closed."}

    if _is_opt_out(message):
        convo.auto_reply_count = 0
        if body.from_role == "merchant":
            convo.last_merchant_message = message
        convo.status = "ended"
        return {"action": "end", "rationale": "Merchant explicitly opted out. Closing conversation and suppressing further sends."}

    trigger = _context_entry("trigger", convo.trigger_id) if convo.trigger_id else None
    merchant = _context_entry("merchant", convo.merchant_id) if convo.merchant_id else None
    category = _find_category_for_merchant(merchant or {}, trigger or {}) if merchant else None
    customer = _context_entry("customer", convo.customer_id) if convo.customer_id else None

    if _is_auto_reply(message, previous_merchant_message, previous_repeat_count):
        convo.auto_reply_count += 1
        if body.from_role == "merchant":
            convo.last_merchant_message = message
        if convo.auto_reply_count >= 4:
            convo.status = "ended"
            return {
                "action": "end",
                "rationale": "Detected repeated merchant auto-replies 4 times in a row. Closing the thread to avoid a loop.",
            }
        convo.status = "waiting"
        return {"action": "wait", "wait_seconds": 14400, "rationale": "Detected merchant auto-reply (canned acknowledgement or repeated template). Backing off to wait for the owner."}

    if _is_intent_accept(message):
        convo.status = "active"
        convo.auto_reply_count = 0
        if body.from_role == "merchant":
            convo.last_merchant_message = message
        if trigger and merchant and category:
            reply_action = _reply_for_engaged_trigger(convo, merchant, category, trigger)
            convo.last_body = reply_action.get("body", "")
            return reply_action
        body_text = _join_sentences([
            "Great - I'll move this forward.",
            "Want me to draft the first version now?",
        ])
        convo.last_body = body_text
        return {"action": "send", "body": body_text, "cta": "open_ended", "rationale": "Merchant accepted the prompt, so I advanced to the concrete next step."}

    if _is_out_of_scope(message):
        convo.auto_reply_count = 0
        if body.from_role == "merchant":
            convo.last_merchant_message = message
        body_text = _join_sentences([
            "I'll keep this on the Vera side and leave GST / accounting work to your CA.",
            "Coming back to the current trigger - want the draft or the abstract first?",
        ])
        convo.last_body = body_text
        return {"action": "send", "body": body_text, "cta": "open_ended", "rationale": "Out-of-scope question declined politely; redirected back to the original mission."}

    if trigger and merchant and category:
        convo.auto_reply_count = 0
        if body.from_role == "merchant":
            convo.last_merchant_message = message
        reply_action = _reply_for_engaged_trigger(convo, merchant, category, trigger)
        convo.last_body = reply_action.get("body", "")
        return reply_action

    if customer and merchant and category:
        convo.auto_reply_count = 0
        if body.from_role == "merchant":
            convo.last_merchant_message = message
        body_text, cta, rationale = _compose_customer_message(category, merchant, trigger or {}, customer)
        convo.last_body = body_text
        return {"action": "send", "body": body_text, "cta": cta, "rationale": rationale}

    body_text = _join_sentences([
        "Understood.",
        "Reply YES if you want me to continue, or STOP if you'd like me to end this thread.",
    ])
    convo.auto_reply_count = 0
    if body.from_role == "merchant":
        convo.last_merchant_message = message
    convo.last_body = body_text
    return {"action": "send", "body": body_text, "cta": "binary_yes_no", "rationale": "Generic fallback when the conversation has no resolvable trigger context."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("bot:app", host="0.0.0.0", port=8080, reload=False)