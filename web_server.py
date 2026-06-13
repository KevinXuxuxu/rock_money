"""Persistent Flask web dashboard for rock_money."""

import logging
import os
from datetime import datetime
from urllib.parse import urlencode

from flask import Flask, flash, redirect, render_template, request, url_for

import analytics
import db

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
    summary = analytics.monthly_summary(months=6)

    max_spend = float(max((r["total_spend"] for r in spend), default=1) or 1)
    for r in spend:
        r["pct"] = float(r["total_spend"]) / max_spend * 100

    total_spend = sum(float(r["total_spend"]) for r in spend)
    current_net = float(summary[-1]["net"]) if summary else 0.0

    return render_template(
        "dashboard.html",
        accounts=accounts,
        recent_txns=recent_txns,
        spend=spend,
        summary=summary,
        month=month,
        total_spend=total_spend,
        current_net=current_net,
    )


@app.get("/accounts")
def accounts_page():
    accounts = analytics.get_accounts()
    return render_template("accounts.html", accounts=accounts)


@app.get("/transactions")
def transactions_page():
    account_id = request.args.get("account") or None
    category = request.args.get("category") or None
    month = request.args.get("month") or None
    pending = request.args.get("pending") == "1"
    limit = min(int(request.args.get("limit", 100)), 500)

    txns = analytics.get_transactions(
        limit=limit,
        account_id=account_id,
        category=category,
        month=month,
        pending=pending,
    )
    accounts = analytics.get_accounts()
    return render_template(
        "transactions.html",
        txns=txns,
        accounts=accounts,
        filters={
            "account": account_id or "",
            "category": category or "",
            "month": month or "",
            "pending": "1" if pending else "",
            "limit": limit,
        },
    )


@app.get("/reports")
def reports_page():
    months = int(request.args.get("months", 12))
    month = request.args.get("month") or datetime.now().strftime("%Y-%m")

    summary = analytics.monthly_summary(months=months)
    spend = analytics.spend_by_category(month)
    budgets = analytics.budget_status(month)

    max_spend = float(max((r["total_spend"] for r in spend), default=1) or 1)
    for r in spend:
        r["pct"] = float(r["total_spend"]) / max_spend * 100

    return render_template(
        "reports.html",
        summary=summary,
        spend=spend,
        budgets=budgets,
        month=month,
        months=months,
    )


@app.get("/search")
def search_page():
    q = request.args.get("q", "")
    month = request.args.get("month") or None
    category = request.args.get("category") or None
    account_id = request.args.get("account") or None
    limit = min(int(request.args.get("limit", 50)), 500)

    txns = []
    if q or month or category or account_id:
        txns = analytics.get_transactions(
            q=q or None,
            month=month,
            category=category,
            account_id=account_id,
            limit=limit,
        )

    accounts = analytics.get_accounts()
    categories = analytics.get_categories()
    views = db.list_views()
    for v in views:
        v["query_string"] = urlencode(
            {k: val for k, val in v["filters"].items() if val}
        )

    return render_template(
        "search.html",
        txns=txns,
        accounts=accounts,
        categories=categories,
        views=views,
        filters={
            "q": q,
            "month": month or "",
            "category": category or "",
            "account": account_id or "",
            "limit": limit,
        },
    )


@app.post("/search/views")
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
    return redirect(url_for("search_page", **active))


@app.post("/search/views/<name>/delete")
def delete_view(name):
    db.delete_view(name)
    return redirect(url_for("search_page"))


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
    rules = db.list_category_rules()
    categories = analytics.get_categories()
    return render_template("rules.html", rules=rules, categories=categories)


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
    return redirect(url_for("rules_page"))


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
