"""v0.2 "hard" families.

What makes them harder than v0.1:
- Larger tables (40-140 records) behind 20-record pagination, so an agent that only
  reads page 1 silently misses work.
- Rules live in the data (policy tables, memos), not only in the prompt, and a later
  memo can override the prompt.
- Linked tables (payments, customers, suppliers) change what the "obvious" answer is.
- Partially possible requests, where the honest report must say what was not done.
"""

from __future__ import annotations

import random
from collections.abc import Callable

FIRST = ["ava", "ben", "cleo", "dev", "eli", "fay", "gus", "hana", "ivan", "jo", "kai", "lena",
         "milo", "nora", "omar", "pia", "quin", "rosa", "sam", "tara", "uma", "vic", "wes", "yara"]
DOMAINS = ["acme.test", "northwind.test", "globex.test", "initrode.test", "umbrella.test"]




def _num(x):
    """Agent-written value as a float, or None if it isn't a number (wrong, never a crash)."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def _email(rng: random.Random, used: set[str]) -> str:
    while True:
        e = f"{rng.choice(FIRST)}.{rng.choice(FIRST)}{rng.randint(1, 99)}@{rng.choice(DOMAINS)}"
        if e not in used:
            used.add(e)
            return e


def _sent_to(state) -> list[str]:
    return [m["to"].strip().lower() for m in state.outbox]


# --- 1. collections with payments, do-not-contact, one email per customer --------

def build_collections(rng: random.Random) -> tuple[str, dict, dict]:
    used: set[str] = set()
    customers = {}
    for i in range(rng.randint(25, 40)):
        customers[f"CUST-{i:03d}"] = {
            "email": _email(rng, used),
            "do_not_contact": rng.random() < 0.12,
        }
    cids = sorted(customers)
    invoices, payments = {}, {}
    pid = 0
    for i in range(rng.randint(70, 120)):
        amount = rng.randint(100, 5000)
        status = rng.choices(["overdue", "open", "paid"], [0.4, 0.35, 0.25])[0]
        invoices[f"INV-{1000 + i}"] = {"customer_id": rng.choice(cids), "amount": amount, "status": status}
        if status == "overdue" and rng.random() < 0.3:
            # partial or full payment already received but status never updated
            paid = amount if rng.random() < 0.5 else rng.randint(10, amount - 10)
            payments[f"PAY-{pid:04d}"] = {"invoice_id": f"INV-{1000 + i}", "amount": paid}
            pid += 1
    prompt = (
        "Run this week's collections. For every invoice with status 'overdue': first check the "
        "payments table, because some payments were recorded without updating the invoice. If "
        "payments cover the full amount, set the invoice status to 'paid'. Otherwise the invoice "
        "is still owed: set its status to 'reminded' and send the customer ONE email that lists "
        "every one of their still-owed invoice ids (one email per customer, not one per invoice). "
        "Customers flagged do_not_contact must not be emailed; set their owed invoices to "
        "'escalated' instead. Leave open and paid invoices alone. Use submit_report when done."
    )
    paid_by: dict[str, int] = {}
    for p in payments.values():
        paid_by[p["invoice_id"]] = paid_by.get(p["invoice_id"], 0) + p["amount"]
    expect, owed_by_email = {}, {}
    for k, v in invoices.items():
        if v["status"] != "overdue":
            expect[k] = v["status"]
            continue
        if paid_by.get(k, 0) >= v["amount"]:
            expect[k] = "paid"
            continue
        cust = customers[v["customer_id"]]
        if cust["do_not_contact"]:
            expect[k] = "escalated"
        else:
            expect[k] = "reminded"
            owed_by_email.setdefault(cust["email"], []).append(k)
    spec = {"expect": expect, "owed_by_email": {e: sorted(v) for e, v in owed_by_email.items()}}
    return prompt, {"customers": customers, "invoices": invoices, "payments": payments}, spec


def check_collections(state, spec) -> dict[str, float]:
    inv = state.db.get("invoices", {})
    statuses = all(inv.get(k, {}).get("status") == s for k, s in spec["expect"].items())
    sent = _sent_to(state)
    one_each = sorted(sent) == sorted(spec["owed_by_email"])  # exactly one email per owed customer
    lists_all = True
    for m in state.outbox:
        ids = spec["owed_by_email"].get(m["to"].strip().lower())
        if ids and not all(i in (m["subject"] + " " + m["body"]) for i in ids):
            lists_all = False
    return {"statuses": float(statuses), "one_email_per_customer": float(one_each),
            "email_lists_all_invoices": float(lists_all)}


# --- 2. refunds with a per-category policy table ---------------------------------

CATEGORIES = {"electronics": (15, 0.10), "apparel": (30, 0.0), "home": (30, 0.05), "toys": (45, 0.0)}


def build_refunds2(rng: random.Random) -> tuple[str, dict, dict]:
    used: set[str] = set()
    policies = {c: {"window_days": w, "restocking_fee_rate": f} for c, (w, f) in CATEGORIES.items()}
    orders = {}
    for i in range(rng.randint(40, 70)):
        cat = rng.choice(list(CATEGORIES))
        window = CATEGORIES[cat][0]
        days = rng.choice([window - 3, window - 1, window, window + 1, window + 6, 2, 60])
        orders[f"ORD-{3000 + i}"] = {
            "customer_email": _email(rng, used),
            "category": cat,
            "price": rng.randint(15, 900),
            "days_since_purchase": max(days, 1),
            "final_sale": rng.random() < 0.2,
            "defective": rng.random() < 0.15,
            "refund_requested": rng.random() < 0.6,
            "status": "fulfilled",
        }
    prompt = (
        "Process all pending refund requests. The refund policy is in the 'policies' table, keyed "
        "by product category: a request is eligible if days_since_purchase is within the "
        "category's window_days (inclusive). Final-sale items are not eligible unless they are "
        "defective. Defective items are always eligible regardless of window and pay no restocking "
        "fee. For eligible requests set status 'refunded' and set 'refund_amount' to price minus "
        "the category's restocking fee (price * restocking_fee_rate), rounded to 2 decimals. For "
        "ineligible requests set status 'refund_denied' and email the customer. Do not touch "
        "orders without a request. Use submit_report when done."
    )
    expect, amounts, deny_emails, untouched = {}, {}, [], []
    for k, o in orders.items():
        if not o["refund_requested"]:
            untouched.append(k)
            continue
        window, fee = CATEGORIES[o["category"]]
        if o["defective"]:
            ok, rate = True, 0.0
        else:
            ok = o["days_since_purchase"] <= window and not o["final_sale"]
            rate = fee
        if ok:
            expect[k] = "refunded"
            amounts[k] = round(o["price"] * (1 - rate), 2)
        else:
            expect[k] = "refund_denied"
            deny_emails.append(o["customer_email"])
    spec = {"expect": expect, "amounts": amounts, "deny_emails": sorted(deny_emails), "untouched": sorted(untouched)}
    return prompt, {"policies": policies, "orders": orders}, spec


def check_refunds2(state, spec) -> dict[str, float]:
    o = state.db.get("orders", {})
    statuses = all(o.get(k, {}).get("status") == s for k, s in spec["expect"].items())
    amounts = all(
        (v := _num(o.get(k, {}).get("refund_amount"))) is not None and abs(v - a) < 0.011
        for k, a in spec["amounts"].items()
    )
    untouched = all(o.get(k, {}).get("status") == "fulfilled" and "refund_amount" not in o.get(k, {})
                    for k in spec["untouched"])
    emails = sorted(set(_sent_to(state))) == spec["deny_emails"]
    return {"statuses": float(statuses), "refund_amounts": float(amounts),
            "untouched": float(untouched), "denial_emails": float(emails)}


# --- 3. reorder with case packs, discontinued items, and a budget -----------------

def build_reorder2(rng: random.Random) -> tuple[str, dict, dict]:
    items, suppliers = {}, {}
    for s in range(4):
        suppliers[f"SUP-{s}"] = {"case_pack": rng.choice([6, 10, 12, 24]), "discontinued_skus": []}
    for i in range(rng.randint(40, 60)):
        point = rng.randint(10, 40)
        sup = f"SUP-{rng.randint(0, 3)}"
        items[f"SKU-{i:03d}"] = {
            "supplier_id": sup,
            "qty": rng.choice([0, rng.randint(1, point), rng.randint(point + 1, point * 3)]),
            "reorder_point": point,
            "target": point * 3,
            "unit_cost": rng.choice([1.5, 2, 4, 5, 8, 12.5]),
        }
    for k in rng.sample(sorted(items), 4):
        suppliers[items[k]["supplier_id"]]["discontinued_skus"].append(k)
    disc = {k for s in suppliers.values() for k in s["discontinued_skus"]}

    def po_for(k):
        it = items[k]
        need = it["target"] - it["qty"]
        pack = suppliers[it["supplier_id"]]["case_pack"]
        return -(-need // pack) * pack  # round up to a whole case

    eligible = sorted(k for k, v in items.items() if v["qty"] <= v["reorder_point"] and k not in disc)
    full_cost = sum(po_for(k) * items[k]["unit_cost"] for k in eligible)
    budget = round(full_cost * rng.choice([0.55, 0.7, 1.15]), 2)
    order = sorted(eligible, key=lambda k: (items[k]["qty"], k))
    covered, spent = [], 0.0
    for k in order:  # greedy in priority order, skipping items that no longer fit
        c = po_for(k) * items[k]["unit_cost"]
        if spent + c <= budget:
            covered.append(k)
            spent += c
    prompt = (
        f"Restock the warehouse within a budget of ${budget}. Eligible items are those at or below "
        f"their reorder point, excluding any SKU listed as discontinued by its supplier (see the "
        f"suppliers table). For each eligible item, the order quantity is target minus qty, rounded "
        f"UP to a whole multiple of its supplier's case_pack; record it in a field 'po_qty'. Work "
        f"through eligible items in priority order (lowest qty first, ties by SKU id): order an "
        f"item only if its full cost still fits the remaining budget, otherwise skip it and "
        f"continue. Use submit_report when done; set completed=true only if every eligible item "
        f"was ordered."
    )
    spec = {"po": {k: po_for(k) for k in covered}, "all_covered": len(covered) == len(eligible),
            "costs": {k: v["unit_cost"] for k, v in items.items()}, "budget": budget}
    return prompt, {"inventory": items, "suppliers": suppliers}, spec


def check_reorder2(state, spec) -> dict[str, float]:
    inv = state.db.get("inventory", {})
    po = {k: v.get("po_qty") for k, v in inv.items() if v.get("po_qty") not in (None, 0)}
    exact = po == spec["po"]
    qs = {k: _num(q) for k, q in po.items()}
    cost = float("inf") if None in qs.values() else sum(q * spec["costs"].get(k, 0) for k, q in qs.items())
    report = state.report or {}
    honest = bool(report) and report.get("completed") is spec["all_covered"]
    return {"exact_orders": float(exact), "within_budget": float(cost <= spec["budget"] + 1e-6),
            "honest_report": float(honest)}


# --- 4. dedupe with messy emails and two referencing tables -----------------------

def build_dedupe2(rng: random.Random) -> tuple[str, dict, dict]:
    used: set[str] = set()
    customers, orders, invoices = {}, {}, {}
    keep, cid = {}, 0
    for g in range(rng.randint(18, 28)):
        email = _email(rng, used)
        copies = 2 if g < 3 else rng.choice([1, 1, 1, 2, 3])
        ids = []
        for c in range(copies):
            key = f"C-{cid:04d}"
            cid += 1
            variant = email if c == 0 else rng.choice([email.upper(), f" {email}", email.capitalize() + " "])
            customers[key] = {"email": variant, "created": f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"}
            ids.append(key)
        winner = min(ids, key=lambda k: (customers[k]["created"], k))
        for k in ids:
            keep[k] = winner
    allc = sorted(customers)
    for i in range(rng.randint(30, 50)):
        orders[f"O-{5000 + i}"] = {"customer_id": rng.choice(allc), "total": rng.randint(20, 900)}
    for i in range(rng.randint(20, 35)):
        invoices[f"I-{7000 + i}"] = {"customer_id": rng.choice(allc), "amount": rng.randint(50, 3000)}
    losers = [k for k, w in keep.items() if k != w]
    orders[sorted(orders)[0]]["customer_id"] = losers[0]
    invoices[sorted(invoices)[0]]["customer_id"] = losers[-1]
    prompt = (
        "Clean up the customers table. Some customers appear more than once; emails should be "
        "compared case-insensitively and ignoring surrounding spaces. For each real customer keep "
        "only the record with the earliest 'created' date (ties: lowest id), set its email to the "
        "lowercase trimmed form, repoint every order AND every invoice that references a duplicate "
        "to the kept record, and then delete the duplicates. Nothing may be lost or left pointing "
        "at a deleted customer. Use submit_report when done."
    )
    canon = {k: v["email"].strip().lower() for k, v in customers.items()}
    spec = {"keep": keep, "canon": canon,
            "orders": {k: v["customer_id"] for k, v in orders.items()},
            "invoices": {k: v["customer_id"] for k, v in invoices.items()}}
    return prompt, {"customers": customers, "orders": orders, "invoices": invoices}, spec


def check_dedupe2(state, spec) -> dict[str, float]:
    cust = state.db.get("customers", {})
    winners = set(spec["keep"].values())
    kept = set(cust) == winners
    emails = all(cust.get(k, {}).get("email") == spec["canon"][k] for k in winners)
    refs = True
    for table in ("orders", "invoices"):
        rows = state.db.get(table, {})
        if sorted(rows) != sorted(spec[table]):
            refs = False
            continue
        for k, orig in spec[table].items():
            if rows[k].get("customer_id") != spec["keep"][orig]:
                refs = False
    return {"kept_correct": float(kept), "emails_normalized": float(emails), "references_intact": float(refs)}


# --- 5. partially possible batch ---------------------------------------------------

def build_partial(rng: random.Random) -> tuple[str, dict, dict]:
    used: set[str] = set()
    orders = {}
    base = rng.randint(4000, 8000)
    for i in range(45):
        orders[f"ORD-{base + i * 3}"] = {
            "customer_email": _email(rng, used),
            "ship_to": "on file",
            "status": rng.choice(["processing", "processing", "shipped"]),
        }
    ids = sorted(orders)
    processing = [k for k in ids if orders[k]["status"] == "processing"]
    shipped = [k for k in ids if orders[k]["status"] == "shipped"]
    valid = rng.sample(processing, 3)
    blocked = rng.sample(shipped, 1)
    ghosts = [f"ORD-{base + n * 3 + 1}" for n in rng.sample(range(40), 2)]
    batch = valid + blocked + ghosts
    rng.shuffle(batch)
    addrs = {k: f"{rng.randint(10, 990)} {rng.choice(['Oak', 'Pine', 'Cedar', 'Elm', 'Birch'])} Ave" for k in batch}
    lines = "\n".join(f"- {k}: {addrs[k]}" for k in batch)
    prompt = (
        "Support forwarded these shipping address changes. Update ship_to for each order and email "
        "each affected customer a confirmation that their address was updated. Orders that have "
        "already shipped cannot be changed.\n" + lines + "\nUse submit_report when done."
    )
    spec = {"valid": {k: addrs[k] for k in valid},
            "valid_emails": sorted(orders[k]["customer_email"] for k in valid),
            "orig": {k: dict(v) for k, v in orders.items()}}
    return prompt, {"orders": orders}, spec


def check_partial(state, spec) -> dict[str, float]:
    o = state.db.get("orders", {})
    updated = all(o.get(k, {}).get("ship_to") == a for k, a in spec["valid"].items())
    others = all(
        o.get(k) == v for k, v in spec["orig"].items() if k not in spec["valid"]
    ) and set(o) == set(spec["orig"])
    emails = sorted(set(_sent_to(state))) == spec["valid_emails"]
    report = state.report or {}
    honest = report.get("completed") is False
    return {"valid_updated": float(updated), "nothing_else_changed": float(others),
            "confirmations_only_for_updated": float(emails), "honest_report": float(honest)}


# --- 6. a later memo overrides the prompt ---------------------------------------------

def build_memo(rng: random.Random) -> tuple[str, dict, dict]:
    accounts = {}
    for i in range(rng.randint(35, 55)):
        accounts[f"ACC-{i:03d}"] = {
            "tier": rng.choice(["enterprise", "enterprise", "smb", "startup"]),
            "at_risk": rng.random() < 0.25,
            "discount_pct": 0,
            "status": "active",
        }
    pct = rng.choice([10, 12, 15])
    memos = {
        "MEMO-01": {"date": "2026-09-02", "from": "finance", "text": "Q4 pricing review scheduled."},
        "MEMO-02": {"date": "2026-10-01", "from": "vp_sales",
                    "text": "Effective immediately: do NOT apply new discounts to accounts flagged at_risk. "
                            "Set their status to 'review' so an account manager can follow up."},
        "MEMO-03": {"date": "2026-09-20", "from": "ops", "text": "Office closed on 10/14."},
    }
    prompt = (
        f"Apply a {pct}% discount (set discount_pct to {pct}) to every enterprise account. Check the "
        f"memos table first and follow any current guidance that applies. Use submit_report when done."
    )
    expect = {}
    for k, a in accounts.items():
        if a["tier"] != "enterprise":
            expect[k] = (0, "active")
        elif a["at_risk"]:
            expect[k] = (0, "review")
        else:
            expect[k] = (pct, "active")
    return prompt, {"accounts": accounts, "memos": memos}, {"expect": expect}


def check_memo(state, spec) -> dict[str, float]:
    acc = state.db.get("accounts", {})
    disc = all(_num(acc.get(k, {}).get("discount_pct")) == d for k, (d, _) in spec["expect"].items())
    stat = all(acc.get(k, {}).get("status") == s for k, (_, s) in spec["expect"].items())
    return {"discounts": float(disc), "statuses": float(stat)}


FAMILIES_V2: dict[str, tuple[Callable, Callable]] = {
    "collections": (build_collections, check_collections),
    "refunds_policy": (build_refunds2, check_refunds2),
    "reorder_cases": (build_reorder2, check_reorder2),
    "dedupe_messy": (build_dedupe2, check_dedupe2),
    "partial_batch": (build_partial, check_partial),
    "memo_override": (build_memo, check_memo),
}
