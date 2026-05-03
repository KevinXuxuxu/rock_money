import os
from typing import Iterator

import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.country_code import CountryCode
from plaid.model.products import Products
from dotenv import load_dotenv

load_dotenv()

_PLAID_ENVS = {
    "sandbox":    plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


def _build_client() -> plaid_api.PlaidApi:
    env_name = os.environ.get("PLAID_ENV", "sandbox").lower()
    configuration = plaid.Configuration(
        host=_PLAID_ENVS[env_name],
        api_key={
            "clientId": os.environ["PLAID_CLIENT_ID"],
            "secret":   os.environ["PLAID_SECRET"],
        },
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


class PlaidClient:
    def __init__(self) -> None:
        self._client = _build_client()

    # ── Link ───────────────────────────────────────────────────────────────────

    def create_link_token(self, user_id: str = "local-user", redirect_uri: str | None = None) -> str:
        kwargs: dict = dict(
            user=LinkTokenCreateRequestUser(client_user_id=user_id),
            client_name="Finance Tracker",
            products=[Products("transactions")],
            country_codes=[CountryCode("US")],
            language="en",
        )
        # Required for OAuth institutions (Chase, BofA, etc.) in production
        if redirect_uri:
            kwargs["redirect_uri"] = redirect_uri
        response = self._client.link_token_create(LinkTokenCreateRequest(**kwargs))
        return response["link_token"]

    def exchange_public_token(self, public_token: str) -> tuple[str, str]:
        """Returns (access_token, item_id)."""
        response = self._client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        )
        return response["access_token"], response["item_id"]

    # ── Item metadata ─────────────────────────────────────────────────────────

    def get_institution_name(self, access_token: str) -> tuple[str | None, str | None]:
        """Returns (institution_id, institution_name)."""
        try:
            item_resp = self._client.item_get(ItemGetRequest(access_token=access_token))
            institution_id = item_resp["item"]["institution_id"]
            if not institution_id:
                return None, None
            inst_resp = self._client.institutions_get_by_id(
                InstitutionsGetByIdRequest(
                    institution_id=institution_id,
                    country_codes=[CountryCode("US")],
                )
            )
            return institution_id, inst_resp["institution"]["name"]
        except Exception:
            return None, None

    # ── Transactions sync ─────────────────────────────────────────────────────

    def sync_transactions(
        self,
        access_token: str,
        cursor: str | None = None,
        count: int = 500,
    ) -> Iterator[dict]:
        """
        Yields one dict per page: {added, modified, removed, next_cursor, has_more, accounts}.
        Caller should loop until has_more is False, saving next_cursor after each page.
        """
        kwargs: dict = {"access_token": access_token, "count": count}
        if cursor:
            kwargs["cursor"] = cursor

        while True:
            request = TransactionsSyncRequest(**kwargs)
            response = self._client.transactions_sync(request)

            accounts = [_parse_account(a) for a in response["accounts"]]
            added    = [_parse_transaction(t) for t in response["added"]]
            modified = [_parse_transaction(t) for t in response["modified"]]
            removed  = [r["transaction_id"] for r in response["removed"]]

            yield {
                "accounts":    accounts,
                "added":       added,
                "modified":    modified,
                "removed":     removed,
                "next_cursor": response["next_cursor"],
                "has_more":    response["has_more"],
            }

            if not response["has_more"]:
                break
            kwargs["cursor"] = response["next_cursor"]


# ── Parsing helpers ────────────────────────────────────────────────────────────

def _parse_account(a) -> dict:
    return {
        "account_id":    a["account_id"],
        "name":          a["name"],
        "official_name": a.get("official_name"),
        "type":          str(a["type"]),
        "subtype":       str(a["subtype"]) if a.get("subtype") else None,
        "mask":          a.get("mask"),
    }


def _parse_transaction(t) -> dict:
    pfc = t.get("personal_finance_category")
    location = t.get("location")
    counterparties = t.get("counterparties")

    return {
        "transaction_id":                       t["transaction_id"],
        "account_id":                           t["account_id"],
        "amount":                               float(t["amount"]),
        "iso_currency_code":                    t.get("iso_currency_code"),
        "date":                                 str(t["date"]),
        "authorized_date":                      str(t["authorized_date"]) if t.get("authorized_date") else None,
        "datetime":                             t.get("datetime"),
        "authorized_datetime":                  t.get("authorized_datetime"),
        "name":                                 t["name"],
        "merchant_name":                        t.get("merchant_name"),
        "payment_channel":                      str(t.get("payment_channel")) if t.get("payment_channel") else None,
        "pending":                              t.get("pending", False),
        "pending_transaction_id":               t.get("pending_transaction_id"),
        "category":                             list(t["category"]) if t.get("category") else None,
        "personal_finance_category":            pfc.get("primary") if pfc else None,
        "personal_finance_category_confidence": pfc.get("confidence_level") if pfc else None,
        "location": {
            "address":    location.get("address"),
            "city":       location.get("city"),
            "region":     location.get("region"),
            "postal_code": location.get("postal_code"),
            "country":    location.get("country"),
            "lat":        location.get("lat"),
            "lon":        location.get("lon"),
        } if location else None,
        "counterparties": [
            {
                "name":              cp.get("name"),
                "type":              str(cp["type"]) if cp.get("type") else None,
                "logo_url":          cp.get("logo_url"),
                "website":           cp.get("website"),
                "entity_id":         cp.get("entity_id"),
                "confidence_level":  cp.get("confidence_level"),
            }
            for cp in counterparties
        ] if counterparties else None,
    }
