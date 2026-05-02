#!/usr/bin/env python3
"""
Standalone bot validation without LLM dependency.
Tests all endpoints and basic functionality.
"""

import json
import time
from urllib.request import Request, urlopen
from urllib.error import URLError


class BotClient:
    def __init__(self, url="http://localhost:8080"):
        self.url = url
    
    def request(self, method, endpoint, body=None):
        """Make HTTP request to bot."""
        try:
            url = f"{self.url}{endpoint}"
            headers = {"Content-Type": "application/json"}
            data = json.dumps(body).encode() if body else None
            
            req = Request(url, data=data, headers=headers, method=method)
            resp = urlopen(req, timeout=10)
            response_data = json.loads(resp.read().decode())
            return response_data, None, resp.status
        except URLError as e:
            # Handle 4xx/5xx responses that raise HTTPError
            if hasattr(e, 'code'):
                try:
                    response_data = json.loads(e.read().decode())
                    return response_data, None, e.code
                except:
                    return None, str(e), e.code
            return None, str(e), None
        except Exception as e:
            return None, str(e), None
    
    def get(self, endpoint):
        return self.request("GET", endpoint)
    
    def post(self, endpoint, body):
        return self.request("POST", endpoint, body)


def test_endpoints():
    """Test all bot endpoints."""
    import time
    client = BotClient()
    timestamp = int(time.time())
    passed = 0
    failed = 0
    
    print("\n" + "="*70)
    print("BOT ENDPOINT VALIDATION TEST".center(70))
    print("="*70 + "\n")
    
    # Test 1: Healthz
    print("[TEST 1] GET /v1/healthz")
    data, err, status = client.get("/v1/healthz")
    if err:
        print(f"  ❌ FAIL: {err}")
        failed += 1
    elif status == 200 and "status" in data:
        print(f"  ✅ PASS: Status={data['status']}, Uptime={data.get('uptime_seconds', '?')}s")
        passed += 1
    else:
        print(f"  ❌ FAIL: Unexpected response")
        failed += 1
    
    # Test 2: Metadata
    print("\n[TEST 2] GET /v1/metadata")
    data, err, status = client.get("/v1/metadata")
    if err:
        print(f"  ❌ FAIL: {err}")
        failed += 1
    elif status == 200 and "team_name" in data:
        print(f"  ✅ PASS: Team={data.get('team_name')}, Model={data.get('model')}")
        passed += 1
    else:
        print(f"  ❌ FAIL: Unexpected response")
        failed += 1
    
    # Test 3: Push Context (category)
    print("\n[TEST 3] POST /v1/context (category)")
    cat_id = f"dentists_{timestamp}"
    cat_payload = {
        "scope": "category",
        "context_id": cat_id,
        "version": 1,
        "payload": {
            "voice": {"register": "professional", "tone": "supportive"},
            "offer_catalog": [{"title": "Cleaning", "price": 299}]
        },
        "delivered_at": "2026-05-01T12:00:00Z"
    }
    data, err, status = client.post("/v1/context", cat_payload)
    if err:
        print(f"  ❌ FAIL: {err}")
        failed += 1
    elif status == 200 and data.get("accepted"):
        print(f"  ✅ PASS: Context accepted, ack_id={data.get('ack_id')}")
        passed += 1
    else:
        print(f"  ❌ FAIL: {data}")
        failed += 1
    
    # Test 4: Push Context (merchant)
    print("\n[TEST 4] POST /v1/context (merchant)")
    merchant_id = f"m_test_dentist_{timestamp}"
    merchant_payload = {
        "scope": "merchant",
        "context_id": merchant_id,
        "version": 1,
        "payload": {
            "merchant_id": merchant_id,
            "category": "dentists",
            "identity": {"name": "Dr. Test", "owner_first_name": "Test"},
            "offers": [{"title": "Cleaning", "status": "active"}],
            "performance": {"delta_7d": {"calls_pct": -0.5}}
        },
        "delivered_at": "2026-05-01T12:00:00Z"
    }
    data, err, status = client.post("/v1/context", merchant_payload)
    if err:
        print(f"  ❌ FAIL: {err}")
        failed += 1
    elif status == 200 and data.get("accepted"):
        print(f"  ✅ PASS: Merchant context accepted")
        passed += 1
    else:
        print(f"  ❌ FAIL: {data}")
        failed += 1
    
    # Test 5: Push Context (trigger)
    print("\n[TEST 5] POST /v1/context (trigger)")
    trigger_id = f"trg_test_{timestamp}"
    trigger_payload = {
        "scope": "trigger",
        "context_id": trigger_id,
        "version": 1,
        "payload": {
            "id": trigger_id,
            "kind": "research_digest",
            "merchant_id": merchant_id,
            "payload": {"category": "dentists", "top_item_id": "d_test"},
            "suppression_key": f"research:test:{timestamp}"
        },
        "delivered_at": "2026-05-01T12:00:00Z"
    }
    data, err, status = client.post("/v1/context", trigger_payload)
    if err:
        print(f"  ❌ FAIL: {err}")
        failed += 1
    elif status == 200 and data.get("accepted"):
        print(f"  ✅ PASS: Trigger context accepted")
        passed += 1
    else:
        print(f"  ❌ FAIL: {data}")
        failed += 1
    
    # Test 6: Tick (compose messages)
    print("\n[TEST 6] POST /v1/tick (compose messages)")
    tick_payload = {
        "now": "2026-05-01T12:00:00Z",
        "available_triggers": [trigger_id]
    }
    data, err, status = client.post("/v1/tick", tick_payload)
    if err:
        print(f"  ❌ FAIL: {err}")
        failed += 1
    elif status == 200 and "actions" in data:
        actions = data.get("actions", [])
        print(f"  ✅ PASS: Tick returned {len(actions)} action(s)")
        if actions:
            for i, action in enumerate(actions[:2], 1):
                body_preview = action.get("body", "")[:60]
                print(f"    - Action {i}: {body_preview}...")
        passed += 1
    else:
        print(f"  ❌ FAIL: {data}")
        failed += 1
    
    # Test 7: Reply (merchant response)
    print("\n[TEST 7] POST /v1/reply (merchant response)")
    conv_id = f"conv_test_{timestamp}"
    reply_payload = {
        "conversation_id": conv_id,
        "merchant_id": merchant_id,
        "from_role": "merchant",
        "message": "Yes, please send the abstract",
        "received_at": "2026-05-01T12:05:00Z",
        "turn_number": 2
    }
    data, err, status = client.post("/v1/reply", reply_payload)
    if err:
        print(f"  ❌ FAIL: {err}")
        failed += 1
    elif status == 200 and "action" in data:
        action = data.get("action")
        print(f"  ✅ PASS: Reply returned action={action}")
        if data.get("body"):
            body_preview = data.get("body", "")[:60]
            print(f"    Body: {body_preview}...")
        passed += 1
    else:
        print(f"  ❌ FAIL: {data}")
        failed += 1
    
    # Test 8: Auto-reply detection
    print("\n[TEST 8] POST /v1/reply (auto-reply detection)")
    conv_id_auto = f"conv_auto_{timestamp}"
    auto_reply_payload = {
        "conversation_id": conv_id_auto,
        "merchant_id": merchant_id,
        "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond shortly.",
        "received_at": "2026-05-01T12:10:00Z",
        "turn_number": 1
    }
    data, err, status = client.post("/v1/reply", auto_reply_payload)
    if err:
        print(f"  ❌ FAIL: {err}")
        failed += 1
    elif status == 200:
        action = data.get("action")
        if action == "wait":
            print(f"  ✅ PASS: Auto-reply correctly detected (action=wait)")
            passed += 1
        else:
            print(f"  ⚠️  UNEXPECTED: Action={action} (expected 'wait')")
            failed += 1
    else:
        print(f"  ❌ FAIL: {data}")
        failed += 1
    
    # Test 9: Stale version handling
    print("\n[TEST 9] POST /v1/context (stale version detection)")
    stale_payload = {
        "scope": "merchant",
        "context_id": merchant_id,
        "version": 1,  # Same version as before - should be rejected
        "payload": {"merchant_id": merchant_id},
        "delivered_at": "2026-05-01T12:15:00Z"
    }
    data, err, status = client.post("/v1/context", stale_payload)
    if err:
        print(f"  ❌ FAIL: {err}")
        failed += 1
    elif status == 409 and not data.get("accepted"):
        print(f"  ✅ PASS: Stale version correctly rejected (409)")
        passed += 1
    else:
        print(f"  ❌ FAIL: Expected 409, got {status}")
        failed += 1
    
    # Summary
    print("\n" + "="*70)
    print(f"RESULTS: {passed} passed, {failed} failed".center(70))
    print("="*70 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    import sys
    success = test_endpoints()
    sys.exit(0 if success else 1)
