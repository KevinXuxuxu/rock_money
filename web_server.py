"""Persistent Flask web dashboard for rock_money."""

import logging
import os
from datetime import datetime, timedelta
from urllib.parse import urlencode

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

import analytics
import db
import sync as sync_mod
from plaid_client import PlaidClient

_plaid: PlaidClient | None = None


def _get_plaid() -> PlaidClient:
    global _plaid
    if _plaid is None:
        _plaid = PlaidClient()
    return _plaid


app = Flask(__name__)
app.secret_key = os.urandom(24)

_log = logging.getLogger(__name__)


@app.template_filter("money")
def money_filter(v):
    return f"${float(v):,.2f}"


@app.template_filter("sign_class")
def sign_class_filter(v):
    return "credit" if float(v) < 0 else "debit"


@app.template_filter("fmt_amount")
def fmt_amount_filter(v):
    f = float(v)
    s = f"${abs(f):,.2f}"
    return f"-{s}" if f < 0 else s


@app.get("/")
def dashboard():
    month = datetime.now().strftime("%Y-%m")
    accounts = analytics.get_accounts()
    recent_txns = analytics.get_transactions(limit=10)
    spend = analytics.spend_by_category(month)
    income = analytics.income_by_category(month)
    summary = analytics.monthly_summary(months=6)

    max_spend = float(max((r["total_spend"] for r in spend), default=1) or 1)
    for r in spend:
        r["pct"] = float(r["total_spend"]) / max_spend * 100

    max_income = float(max((r["total_income"] for r in income), default=1) or 1)
    for r in income:
        r["pct"] = float(r["total_income"]) / max_income * 100

    total_spend = sum(float(r["total_spend"]) for r in spend)
    total_income = sum(float(r["total_income"]) for r in income)
    current_net = float(summary[-1]["net"]) if summary else 0.0

    return render_template(
        "dashboard.html",
        accounts=accounts,
        recent_txns=recent_txns,
        spend=spend,
        income=income,
        summary=summary,
        month=month,
        total_spend=total_spend,
        total_income=total_income,
        current_net=current_net,
    )


@app.get("/accounts")
def accounts_page():
    accounts = analytics.get_accounts()
    return render_template("accounts.html", accounts=accounts)


@app.post("/accounts/items/<item_id>/remove")
def remove_item(item_id):
    item = db.get_item(item_id)
    if not item:
        flash("Institution not found.", "error")
        return redirect(url_for("accounts_page"))
    name = item.get("institution_name") or item_id
    if os.environ.get("PLAID_SKIP_REVOKE"):
        _log.info("PLAID_SKIP_REVOKE set — skipping Plaid revoke for %s", item_id)
    else:
        try:
            _get_plaid().remove_item(item["access_token"])
        except Exception as exc:
            _log.warning("Plaid revoke failed for %s: %s", item_id, exc)
    db.delete_item(item_id)
    flash(f"Removed '{name}' and all associated data.", "success")
    return redirect(url_for("accounts_page"))


@app.post("/accounts/sync")
def sync_accounts():
    try:
        sync_mod.sync_all()
        flash("Sync complete.", "success")
    except Exception as exc:
        _log.error("sync failed: %s", exc)
        flash(f"Sync failed: {exc}", "error")
    return redirect(url_for("accounts_page"))


@app.get("/api/link-token")
def api_link_token():
    import os

    try:
        redirect_uri = os.environ.get("PLAID_REDIRECT_URI") or None
        token = _get_plaid().create_link_token(redirect_uri=redirect_uri)
        return jsonify({"link_token": token})
    except Exception as exc:
        _log.error("create_link_token failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.post("/api/exchange")
def api_exchange():
    data = request.get_json(force=True)
    public_token = data.get("public_token")
    if not public_token:
        return jsonify({"ok": False, "error": "missing public_token"}), 400
    try:
        access_token, item_id = _get_plaid().exchange_public_token(public_token)
        institution_id, institution_name = _get_plaid().get_institution_name(
            access_token
        )
        db.upsert_item(item_id, access_token, institution_id, institution_name)
        _log.info("linked institution: %s (item_id=%s)", institution_name, item_id)
        return jsonify({"ok": True, "institution_name": institution_name})
    except Exception as exc:
        _log.error("exchange failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/transactions")
def transactions_page():
    q = request.args.get("q", "").strip() or None
    account_id = request.args.get("account") or None
    category = request.args.get("category") or None
    month = request.args.get("month") or None
    pending_only = request.args.get("pending") == "1"
    limit = min(int(request.args.get("limit", 100)), 500)

    txns = analytics.get_transactions(
        q=q,
        limit=limit,
        account_id=account_id,
        category=category,
        month=month,
        pending_only=pending_only,
    )
    accounts = analytics.get_accounts()
    categories = analytics.get_categories()
    views = db.list_views()
    for v in views:
        v["query_string"] = urlencode(
            {k: val for k, val in v["filters"].items() if val}
        )

    return render_template(
        "transactions.html",
        txns=txns,
        accounts=accounts,
        categories=categories,
        views=views,
        filters={
            "q": q or "",
            "account": account_id or "",
            "category": category or "",
            "month": month or "",
            "pending": "1" if pending_only else "",
            "limit": limit,
        },
    )


@app.get("/search")
def search_page():
    return redirect(url_for("transactions_page", **request.args), 301)


@app.get("/reports")
def reports_page():
    this_month = datetime.now().strftime("%Y-%m")
    month = request.args.get("month") or this_month
    # Clamp to the current month — there's no data in the future.
    if month > this_month:
        month = this_month
    cur = datetime.strptime(month, "%Y-%m")

    prev_m = (cur.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    next_dt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    next_m = next_dt.strftime("%Y-%m")
    is_current = month >= this_month
    month_label = cur.strftime("%B %Y")

    summary = analytics.monthly_summary(months=6)
    spend = analytics.spend_by_category(month)
    income = analytics.income_by_category(month)
    budgets = analytics.budget_status(month)

    max_spend = float(max((r["total_spend"] for r in spend), default=1) or 1)
    for r in spend:
        r["pct"] = float(r["total_spend"]) / max_spend * 100

    max_income = float(max((r["total_income"] for r in income), default=1) or 1)
    for r in income:
        r["pct"] = float(r["total_income"]) / max_income * 100

    return render_template(
        "reports.html",
        summary=summary,
        spend=spend,
        income=income,
        budgets=budgets,
        month=month,
        month_label=month_label,
        prev_month=prev_m,
        next_month=next_m,
        is_current=is_current,
    )


@app.post("/transactions/views")
def save_view():
    name = request.form.get("name", "").strip()
    filters = {
        "q": request.form.get("q", ""),
        "month": request.form.get("month", ""),
        "category": request.form.get("category", ""),
        "account": request.form.get("account", ""),
    }
    if name:
        db.upsert_view(name, filters)
    active = {k: v for k, v in filters.items() if v}
    return redirect(url_for("transactions_page", **active))


@app.post("/transactions/views/<name>/delete")
def delete_view(name):
    db.delete_view(name)
    return redirect(url_for("transactions_page"))


@app.get("/transactions/<txn_id>")
def transaction_detail(txn_id):
    txn = analytics.get_transaction_detail(txn_id)
    if not txn:
        return "Transaction not found", 404
    return render_template("transaction_detail.html", txn=txn)


@app.post("/transactions/<txn_id>/note")
def set_note(txn_id):
    note = request.form.get("note", "").strip()
    if note:
        db.upsert_transaction_note(txn_id, note)
    else:
        db.delete_transaction_note(txn_id)
    return redirect(url_for("transaction_detail", txn_id=txn_id))


@app.post("/transactions/<txn_id>/tags/add")
def add_tag(txn_id):
    tag = request.form.get("tag", "").strip().lower()
    if tag:
        db.add_transaction_tag(txn_id, tag)
    return redirect(url_for("transaction_detail", txn_id=txn_id))


@app.post("/transactions/<txn_id>/tags/remove")
def remove_tag(txn_id):
    tag = request.form.get("tag", "").strip()
    db.remove_transaction_tag(txn_id, tag)
    return redirect(url_for("transaction_detail", txn_id=txn_id))


@app.post("/transactions/<txn_id>/category")
def set_category_web(txn_id):
    category = request.form.get("category", "").strip()
    if category:
        db.upsert_category_override(txn_id, category)
    else:
        db.delete_category_override(txn_id)
    return redirect(url_for("transaction_detail", txn_id=txn_id))


@app.get("/rules")
def rules_page():
    q = request.args.get("q", "").strip() or None
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    per_page = 20

    total = db.count_category_rules(search=q)
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, pages)
    rules = db.list_category_rules(
        search=q, limit=per_page, offset=(page - 1) * per_page
    )
    total_all = db.count_category_rules() if q else total
    categories = analytics.get_categories()

    return render_template(
        "rules.html",
        rules=rules,
        categories=categories,
        q=q or "",
        page=page,
        pages=pages,
        per_page=per_page,
        total=total,
        total_all=total_all,
    )


@app.post("/rules")
def add_rule():
    pattern = request.form.get("match_pattern", "").strip()
    field = request.form.get("match_field", "merchant_name")
    category = request.form.get("category", "").strip()
    priority = int(request.form.get("priority", 0) or 0)
    _log.info(
        "add_rule: received pattern=%r field=%r category=%r priority=%r",
        pattern,
        field,
        category,
        priority,
    )
    if pattern and category:
        rule_id = db.add_category_rule(
            match_pattern=pattern,
            match_field=field,
            category=category,
            priority=priority,
        )
        _log.info("add_rule: saved as rule #%d", rule_id)
        flash(
            f"Rule #{rule_id} added: {field} contains '{pattern}' → {category}",
            "success",
        )
    else:
        _log.warning(
            "add_rule: NOT saved — pattern=%r category=%r (one or both empty)",
            pattern,
            category,
        )
        flash("Rule not saved: both pattern and category are required.", "error")
    return redirect(url_for("rules_page"))


@app.post("/rules/<int:rule_id>/delete")
def delete_rule(rule_id):
    db.delete_category_rule(rule_id)
    flash(f"Rule #{rule_id} deleted.", "info")
    # Return to the page the user was browsing (search + page travel in the form).
    q = request.form.get("q", "").strip() or None
    try:
        page = max(1, int(request.form.get("page", 1)))
    except ValueError:
        page = 1
    return redirect(url_for("rules_page", q=q, page=page if page > 1 else None))


@app.post("/rules/apply")
def apply_rules_web():
    dry_run = request.form.get("dry_run") == "1"
    results = analytics.apply_rules(dry_run=dry_run)
    n = len(results)
    if dry_run:
        flash(f"Dry run: would match {n} transaction(s).", "info")
    else:
        flash(f"Applied rules: matched and categorised {n} transaction(s).", "success")
    return redirect(url_for("rules_page"))


def run(port: int = 5000) -> None:
    print(f"Dashboard running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
