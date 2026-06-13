"""
Temporary Flask server for the Plaid Link flow.
Run via `python main.py link` — starts the server, opens the browser,
then shuts down automatically after a successful account link.
"""
import threading
import webbrowser

from flask import Flask, jsonify, render_template, request

import db
from plaid_client import PlaidClient

app = Flask(__name__)
_shutdown_event = threading.Event()
_client = PlaidClient()
_redirect_uri: str | None = None  # set in run()


@app.get("/")
def index():
    return render_template("link.html")


@app.get("/api/link-token")
def link_token():
    try:
        token = _client.create_link_token(redirect_uri=_redirect_uri)
        return jsonify({"link_token": token})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/exchange")
def exchange():
    data = request.get_json(force=True)
    public_token = data.get("public_token")
    if not public_token:
        return jsonify({"ok": False, "error": "missing public_token"}), 400

    try:
        access_token, item_id = _client.exchange_public_token(public_token)
        institution_id, institution_name = _client.get_institution_name(access_token)
        db.upsert_item(item_id, access_token, institution_id, institution_name)
        print(f"\n  Linked: {institution_name or item_id} (item_id={item_id})")
        # Signal main thread to shut down after response is sent
        threading.Timer(1.0, _shutdown_event.set).start()
        return jsonify({"ok": True, "institution_name": institution_name})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def run(port: int = 8765) -> None:
    """Open browser and start Flask. Blocks until a successful link."""
    global _redirect_uri
    import os
    local_url = f"http://localhost:{port}"
    # Plaid production rejects http:// redirect URIs; use PLAID_REDIRECT_URI
    # (e.g. an ngrok https URL) for OAuth institutions in production.
    _redirect_uri = os.environ.get("PLAID_REDIRECT_URI") or None
    if _redirect_uri:
        print(f"OAuth redirect URI: {_redirect_uri}")
    else:
        print("No PLAID_REDIRECT_URI set — OAuth institutions (Chase, BofA, etc.) will not be available.")
        print("To enable them: run `ngrok http 8765`, set PLAID_REDIRECT_URI=https://<your-ngrok-url>,")
        print("and add that URL to Plaid dashboard → Team Settings → API → Allowed redirect URIs.\n")
    print(f"Opening Plaid Link at {local_url}")
    print("Complete the bank connection in your browser. This server will stop automatically.\n")
    webbrowser.open(local_url)

    server_thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    _shutdown_event.wait()
    print("\nAccount linked successfully. Server stopped.")
