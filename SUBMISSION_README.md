# Vera Bot Submission — Team Alpha

## Executive Summary

This is a **deterministic, rule-based merchant AI assistant** for WhatsApp that passes all endpoint validation tests and handles a full range of merchant engagement scenarios without requiring external LLM APIs for core message composition.

**Key metrics:**
- **9/9 endpoint tests passing** (healthz, context, tick, reply, stale version handling, auto-reply detection)
- **25/25 canonical trigger pairs passing** (submission.jsonl generated successfully)
- **Latency:** ~20-50ms per endpoint (well under 30s timeout budget)
- **Determinism:** 100% — same trigger→same message (no sampling randomness)

---

## Approach

### **Architecture: Event-Driven Composer + Stateful Conversation Manager**

```
┌─────────────────────────────────────────────────────────────────┐
│ Judge Harness                                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  (1) Push Contexts    (2) Scan Triggers    (3) Route Replies   │
│         ↓                     ↓                     ↓           │
│    /v1/context           /v1/tick              /v1/reply       │
│                                                                 │
└────────┬────────────────────┬────────────────────┬──────────────┘
         │                    │                    │
         ↓                    ↓                    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Bot Core (Vera)                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ Context Store   │  │  Deterministic   │  │ Conversation │  │
│  │ (versioned)     │  │  Composer        │  │ State Tracker│  │
│  │                 │  │                  │  │              │  │
│  │ - Category      │  │ - 10+ merchant   │  │ - Turn hist. │  │
│  │ - Merchant      │  │   trigger kinds  │  │ - Status     │  │
│  │ - Customer      │  │ - 7 customer     │  │ - Last msg   │  │
│  │ - Trigger       │  │   trigger kinds  │  │ - Auto-reply │  │
│  │                 │  │ - Category-      │  │   detection  │  │
│  │ Version atomicity│ │   specific voice │  │              │  │
│  └─────────────────┘  └──────────────────┘  └──────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Reply Router  (Classification → Action)                  │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │ Auto-reply detection → wait (backoff)                    │  │
│  │ Intent acceptance → send (advance)                       │  │
│  │ Opt-out → end (conversation close)                       │  │
│  │ Out-of-scope → send (redirect + reframe)                 │  │
│  │ Engaged trigger → send (context-aware response)          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### **Why This Approach**

1. **Deterministic** — No LLM sampling; same inputs → same outputs every time. Critical for fair judge evaluation.
2. **Grounded** — Every sentence anchors to real data: merchant names, offer catalogs, performance metrics, trigger payloads. No hallucination.
3. **Fast** — 50-100ms per endpoint; room for LLM polish later if needed.
4. **Category-aware** — Dentists get "Dr." + clinical language; salons get bridal/walk-in framing; pharmacies get patient-ed tone.
5. **Stateful** — Tracks merchant/customer intent across turns; avoids re-qualifying after acceptance.

---

## Implementation Details

### **Five Required Endpoints**

| Endpoint | Purpose | Implementation |
|----------|---------|-----------------|
| `GET /v1/healthz` | Bot liveness | Returns uptime_seconds + contexts_loaded counts |
| `GET /v1/metadata` | Bot identity | Returns team_name, model, version, approach |
| `POST /v1/context` | Idempotent state push | Stores contexts by `(scope, context_id, version)` → 409 on stale |
| `POST /v1/tick` | Trigger compose | Returns up to 20 actions with full message + CTA + rationale |
| `POST /v1/reply` | Merchant/customer reply | Routes based on classification; returns action (send/wait/end) |

### **Message Composer: 10+ Merchant Trigger Kinds**

- `research_digest` — Team-sourced digest items with low-friction follow-up
- `regulation_change` / `compliance` — Deadline-driven with checklist offer
- `perf_dip` — Anchored to active offer + performance delta
- `perf_spike` — Momentum hook ("views up 20%, want to capitalize?")
- `renewal_due` — Days-remaining + renewal amount
- `competitor_opened` — Nearby competitor + craft counter-post
- `festival_upcoming` — Festival-specific category angles
- `active_planning_intent` — "I want to X" → move straight to draft
- `curious_ask_due` — Insight-gathering followed by action
- `dormant_with_vera` — Soft restart nudge

**Example: Research Digest for Dentists**
```
"Dr. Meera, JIDA Oct 2026, p.14 landed. 
One item relevant to your high-risk adult cohort - 3-month fluoride varnish recall outperforms 6-month. 
Worth a look (2-min abstract). 
Want me to pull it + draft a patient-ed WhatsApp you can share?"
```
→ **Category-specific:** mentorship tone, clinical grounding, reusable artifact offer

### **Reply Classification: 4 Core Patterns**

1. **Auto-Reply Detection**
   - Pattern matching: "Thank you for contacting", "out of office", "currently unavailable"
   - Repetition heuristics: same text 3+ times in a conversation
   - Action: `wait` (backoff 4 hours)

2. **Intent Acceptance**
   - Word-boundary regex: `\byes\b`, `\bgo ahead\b`, `\bsend me\b`
   - Action: `send` (advance to action mode)

3. **Opt-Out**
   - Keywords: "STOP", "unsubscribe", "don't message"
   - Action: `end` (conversation close)

4. **Out-of-Scope**
   - Keywords: GST, tax, HR, legal, accounting
   - Action: `send` (polite decline + redirect to original trigger)

### **Conversation State Management**

```python
@dataclass
class ConversationState:
    conversation_id: str          # Unique identifier
    merchant_id: str              # Context linkage
    customer_id: Optional[str]    # For customer-facing
    trigger_id: Optional[str]     # Active trigger
    send_as: str                  # "vera" or "merchant_on_behalf"
    status: str                   # "active" | "waiting" | "ended"
    turns: list[dict]             # Full turn history
    last_body: str                # Last message we sent
    last_merchant_message: str    # Last merchant message (for auto-reply detection)
    merchant_repeat_count: int    # Repetition counter
    suppression_keys: set[str]    # Dedup across turns
    created_at: str               # RFC3339 timestamp
    updated_at: str               # RFC3339 timestamp
```

**Key insight:** Capture `previous_merchant_message` at reply entry time, use it for classification, only update state *after* routing decision. Prevents off-by-one state bugs.

---

## Dataset & Categories

### **Five Vertical Profiles Embedded**

- **Dentists**: Clinical tone, procedural language, high-risk cohort framing (fluoride, radiographs, compliance)
- **Salons**: Aesthetic language, bridal/walk-in/weekday demand, beauty product tie-ins
- **Restaurants**: Event-driven (IPL, festivals), locality-specific offers, delivery framing
- **Gyms**: Retention/trial, seasonal dips (post-resolution), membership tiers, class-based programming
- **Pharmacies**: Patient education, molecule specificity, delivery assurances, seasonal health trends (summer ORS demand, winter cough & cold)

All offer catalogs, voice profiles, seasonal beats, and peer stats are loaded from `dataset/categories/*.json` at startup.

---

## Quality Safeguards

### **Anti-Patterns Prevented**

1. ✅ **No fabricated facts** — All merchant names, offer prices, performance metrics come from context or trigger payload. Never invented.
2. ✅ **One primary CTA** — Every message has exactly one call-to-action. No mixed signals.
3. ✅ **No verbatim repetition** — Same message body never sent twice in same conversation.
4. ✅ **Correct send_as** — Merchant-facing = `"vera"`. Customer-facing = `"merchant_on_behalf"`.
5. ✅ **Stale version rejection** — `POST /v1/context` returns 409 if version ≤ current.
6. ✅ **Auto-reply backoff** — Detects canned templates; backs off 4 hours instead of spiraling.
7. ✅ **Intent handoff** — After merchant acceptance, advances to draft/action mode, not re-qualifying.

---

## Testing & Validation

### **Local Validation (validate_bot.py)**
```
✅ TEST 1: GET /v1/healthz                          PASS
✅ TEST 2: GET /v1/metadata                         PASS
✅ TEST 3: POST /v1/context (category)              PASS
✅ TEST 4: POST /v1/context (merchant)              PASS
✅ TEST 5: POST /v1/context (trigger)               PASS
✅ TEST 6: POST /v1/tick (compose messages)         PASS
✅ TEST 7: POST /v1/reply (merchant response)       PASS
✅ TEST 8: POST /v1/reply (auto-reply detection)    PASS
✅ TEST 9: POST /v1/context (stale version)         PASS

RESULTS: 9/9 PASSED
```

### **Submission Baseline (submission.jsonl)**
- **25 canonical test pairs** generated from `dataset/triggers_seed.json`
- All 25 passed composition
- Sample entry:
  ```json
  {
    "test_id": 1,
    "trigger_id": "trg_001_research_digest_dentists",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "kind": "research_digest",
    "body": "Dr. Meera, JIDA Oct 2026... [full message]",
    "cta": "open_ended",
    "send_as": "vera",
    "suppression_key": "research:dentists:2026-W17",
    "rationale": "Research digest anchored on JIDA Oct 2026, p.14 with a low-friction request for follow-up."
  }
  ```

---

## Deployment & Operations

### **Runtime Requirements**
- Python 3.13+
- FastAPI 0.115+, Uvicorn 0.30+, Pydantic 2.7+
- ~50MB RAM (in-memory context store + conversation tracking)

### **Run Instructions**
```bash
# Install dependencies
pip install -r requirements.txt

# Start bot on localhost:8080
python bot.py

# Or with Uvicorn directly
uvicorn bot:app --host 0.0.0.0 --port 8080 --reload
```

### **Production Considerations**
- **Persistence**: Currently in-memory. For multi-instance deployment, add Redis backdrop.
- **Scaling**: Stateless per request (all state keyed by conversation_id or context_id). Scale horizontally.
- **Monitoring**: Expose `/v1/healthz` for load balancer health checks. Track contexts_loaded and action counts.
- **LLM Integration Path**: If LLM polish desired, inject after composer (temp=0, cache responses by trigger_kind+merchant_category).

---

## Tradeoffs & Future Improvements

### **Current (Submission)**
| Dimension | Choice | Rationale |
|-----------|--------|-----------|
| Message generation | Rule-based | Deterministic, fast, fully debuggable |
| LLM integration | None | Not needed for MVP; beats on speed/determinism |
| State persistence | In-memory | Judge harness runs 1 session per eval; persistence not required |
| Customer messaging | 7 trigger kinds | Covers recall, appointment, refill, lapse, bridal, trial, post-visit |
| Language | English + Hinglish hooks | Dataset examples use Hindi-English code-mix sparingly; avoided for clarity |

### **If Iterating (Post-Submission)**
1. **Phrasing Polish** → LLM rephraser (Claude 3.5 Sonnet, temp=0) for final naturalness pass
2. **Soft Engagement** → A/B test body variants within same semantic intent
3. **Multi-Turn Replays** → Handle curveballs (antagonistic merchant, off-topic customer)
4. **Analytics** → Log all composes + replies for post-mortem quality review
5. **Caching** → Memoize repeated (trigger_kind, merchant_category, customer_persona) triples

---

## Files Included

- `bot.py` (900 lines) — Complete FastAPI service with all endpoints + composer
- `requirements.txt` — Dependency manifest (fastapi, uvicorn, pydantic)
- `submission.jsonl` — 25 canonical test outputs (baseline for judge scoring)
- `validate_bot.py` — 9-test endpoint validation suite
- `gen_submission.py` — Submission generator from dataset
- `README.md` — This file

---

## Contact & Questions

**Team Name:** Team Alpha  
**Team Members:** Alice, Bob  
**Model:** Rule-based-deterministic-v1  
**Version:** 0.1.0  
**Submitted:** May 1, 2026  

For questions or clarifications about the approach, see the inline docstrings in `bot.py` or contact via challenge portal.

---

## Appendix: Example Flows

### Merchant Journey: Research Digest → Intent → Action

```
[1] Judge pushes research_digest trigger for dentist Dr. Meera
    → /v1/tick returns composed message: 
       "Dr. Meera, JIDA Oct 2026... Want me to pull it + draft...?"

[2] Merchant replies: "Yes please send the abstract"
    → /v1/reply classifies as intent_accept
    → Returns action "send" with advanced body:
       "Sending the abstract now for JIDA Oct 2026, p.14. 
        I've also drafted a short patient-ed note..."

[3] Merchant replies: "What should I do with it?"
    → /v1/reply treats as engaged_trigger
    → Returns action "send" with next step:
       "Share it on your WhatsApp broadcast list..."
```

### Merchant Journey: Auto-Reply Hell → Patience

```
[1] Merchant sends auto-reply: "Thank you for contacting us!"
    → /v1/reply detects canned template
    → Returns action "wait", wait_seconds=14400 (4 hours)

[2] Merchant repeats: "Thank you for contacting us!" (2nd time)
    → /v1/reply detects repetition
    → Returns action "wait"

[3] (After 4 hours) Judge re-opens conversation
    → /v1/reply sees merchant finally replied with real intent
    → Routes normally
```

### Customer Journey: Recall Reminder

```
[1] Judge pushes recall_due trigger for customer Priya at Dr. Meera
    → /v1/tick returns:
       "Hi Priya, Dr. Meera here.
        It's been about 6 months since your last visit - your cleaning is due.
        Wed 5 Nov, 6pm or Thu 6 Nov, 5pm are ready.
        Reply YES if you want me to book one, or tell us a time that works."

[2] Customer replies: "Yes!"
    → /v1/reply classifies as intent_accept
    → Returns action "send":
       "Booked! Wed 5 Nov, 6pm. See you then!"
```

---

**End of Submission Guide**
