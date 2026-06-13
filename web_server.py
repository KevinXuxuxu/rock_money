"""Persistent Flask web dashboard for rock_money."""

from datetime import datetime

from flask import Flask, render_template, request

import analytics

app = Flask(__name__)


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


def run(port: int = 5000) -> None:
    print(f"Dashboard running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
