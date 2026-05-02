#!/usr/bin/env python3
"""
Generate submission.jsonl from the bot's composer logic.
Produces JSON lines for the 30 canonical test pairs.
"""

import json
import sys
from pathlib import Path
from bot import compose


def load_dataset():
    """Load all contexts from dataset JSON files."""
    dataset_dir = Path(__file__).parent / "dataset"
    
    categories = {}
    merchants = {}
    customers = {}
    triggers = {}
    
    # Load categories
    for cat_file in dataset_dir.glob("categories/*.json"):
        with open(cat_file) as f:
            data = json.load(f)
            slug = cat_file.stem
            if "voice" in data:
                categories[slug] = data
            else:
                # Handle wrapped format
                for key, value in data.items():
                    if key != "_README":
                        categories[key] = value
    
    # Load merchants
    with open(dataset_dir / "merchants_seed.json") as f:
        data = json.load(f)
        for merchant in data.get("merchants", []):
            merchants[merchant.get("merchant_id")] = merchant
    
    # Load customers
    with open(dataset_dir / "customers_seed.json") as f:
        data = json.load(f)
        for customer in data.get("customers", []):
            customers[customer.get("customer_id")] = customer
    
    # Load triggers
    with open(dataset_dir / "triggers_seed.json") as f:
        data = json.load(f)
        for trigger in data.get("triggers", []):
            triggers[trigger.get("id")] = trigger
    
    return categories, merchants, customers, triggers


def generate_submissions():
    """Generate submission.jsonl entries."""
    categories, merchants, customers, triggers = load_dataset()
    
    # Take first 30 triggers (or all if fewer)
    trigger_ids = list(triggers.keys())[:30]
    
    results = []
    
    print(f"[INFO] Loaded {len(categories)} categories, {len(merchants)} merchants, "
          f"{len(customers)} customers, {len(triggers)} triggers")
    print(f"[INFO] Processing {len(trigger_ids)} canonical trigger pairs...")
    
    for test_id, trigger_id in enumerate(trigger_ids, 1):
        trigger = triggers[trigger_id]
        
        # Get merchant
        merchant_id = trigger.get("merchant_id")
        merchant = merchants.get(merchant_id)
        if not merchant:
            print(f"[WARN] Test {test_id}: Merchant {merchant_id} not found, skipping")
            continue
        
        # Get category from trigger payload or merchant
        category_slug = (trigger.get("payload") or {}).get("category")
        if not category_slug:
            category_slug = merchant.get("category_slug") or merchant.get("category")
        
        category = categories.get(category_slug)
        if not category:
            print(f"[WARN] Test {test_id}: Category {category_slug} not found, skipping")
            continue
        
        # Get customer if customer-scoped
        customer = None
        if trigger.get("scope") == "customer":
            customer_id = trigger.get("customer_id")
            customer = customers.get(customer_id)
            if not customer:
                print(f"[WARN] Test {test_id}: Customer {customer_id} not found, skipping")
                continue
        
        # Compose message
        try:
            composed = compose(category, merchant, trigger, customer)
            
            entry = {
                "test_id": test_id,
                "trigger_id": trigger_id,
                "merchant_id": merchant_id,
                "customer_id": trigger.get("customer_id"),
                "scope": trigger.get("scope"),
                "kind": trigger.get("kind"),
                "body": composed.get("body", ""),
                "cta": composed.get("cta", ""),
                "send_as": composed.get("send_as", ""),
                "suppression_key": composed.get("suppression_key", ""),
                "rationale": composed.get("rationale", ""),
            }
            
            results.append(entry)
            print(f"[PASS] Test {test_id}: {trigger_id}")
            
        except Exception as e:
            print(f"[FAIL] Test {test_id}: {trigger_id} — {e}")
            results.append({
                "test_id": test_id,
                "trigger_id": trigger_id,
                "error": str(e)
            })
    
    return results


def main():
    print("\n=== Generating submission.jsonl ===\n")
    
    try:
        results = generate_submissions()
        
        # Write JSONL
        output_path = Path(__file__).parent / "submission.jsonl"
        with open(output_path, "w") as f:
            for entry in results:
                f.write(json.dumps(entry) + "\n")
        
        print(f"\n[SUCCESS] Generated {len(results)} entries to {output_path}")
        
        # Summary
        passed = sum(1 for r in results if "error" not in r)
        failed = sum(1 for r in results if "error" in r)
        print(f"[SUMMARY] Passed: {passed}, Failed: {failed}")
        
        return 0 if failed == 0 else 1
        
    except Exception as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
