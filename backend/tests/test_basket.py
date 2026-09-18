"""Port of backend/test/cart.test.js (the app-side Basket, not the store cart)."""

from __future__ import annotations

import pytest

from app.services import basket


def test_writes_reads_and_normalizes_a_session_basket(session):
    saved = basket.write(
        session,
        {
            "ignored": True,
            "items": [
                {
                    "ingredient": " Tomato ",
                    "quantity": "2 kg",
                    "status": "found",
                    "count": 2,
                    "product": {
                        "name": " Fresh Tomatoes 1 kg ",
                        "packSize": "1 kg",
                        "price": "₹40",
                        "junk": "x",
                    },
                },
                {"ingredient": "Star anise", "status": "not_found"},
            ],
        },
    )

    assert saved == {
        "items": [
            {
                "ingredient": "Tomato",
                "quantity": "2 kg",
                "status": "found",
                "product": {
                    "name": "Fresh Tomatoes 1 kg",
                    "packSize": "1 kg",
                    "price": "₹40",
                },
                "count": 2,
            },
            {"ingredient": "Star anise", "status": "not_found"},
        ]
    }

    assert basket.read(session) == (True, saved)


def test_a_found_item_with_no_usable_product_is_downgraded(session):
    saved = basket.write(
        session, {"items": [{"ingredient": "Rice", "status": "found", "product": {"name": "   "}}]}
    )
    assert saved["items"] == [{"ingredient": "Rice", "status": "not_found"}]


def test_count_defaults_to_one(session):
    saved = basket.write(
        session,
        {"items": [{"ingredient": "Milk", "status": "found", "product": {"name": "Amul 500 ml"}}]},
    )
    assert saved["items"][0]["count"] == 1


def test_set_count_updates_pack_count_with_min_of_one(session):
    basket.write(
        session,
        {
            "items": [
                {
                    "ingredient": "Tomato",
                    "status": "found",
                    "count": 1,
                    "product": {"name": "Tomatoes 1 kg"},
                }
            ]
        },
    )

    assert basket.set_count(session, "Tomato", 3)["items"][0]["count"] == 3
    assert basket.set_count(session, "Tomato", 0)["items"][0]["count"] == 1

    with pytest.raises(ValueError, match="was not found"):
        basket.set_count(session, "Nope", 2)


def test_remove_item_drops_a_line_by_ingredient_name(session):
    basket.write(
        session,
        {
            "items": [
                {"ingredient": "Tomato", "status": "found", "product": {"name": "Tomatoes 1 kg"}},
                {"ingredient": "Paneer", "status": "found", "product": {"name": "Paneer 200 g"}},
            ]
        },
    )

    updated = basket.remove_item(session, "Tomato")
    assert [item["ingredient"] for item in updated["items"]] == ["Paneer"]


def test_rejects_items_without_an_ingredient_name(session):
    with pytest.raises(ValueError, match=r"items\[0\]\.ingredient must be a non-empty string"):
        basket.write(session, {"items": [{"ingredient": "", "status": "not_found"}]})


def test_optional_product_fields_are_dropped_when_blank(session):
    saved = basket.write(
        session,
        {
            "items": [
                {
                    "ingredient": "Rice",
                    "status": "found",
                    "product": {"name": "Basmati", "packSize": "  ", "rating": "4.4"},
                }
            ]
        },
    )
    product = saved["items"][0]["product"]
    assert product == {"name": "Basmati", "rating": "4.4"}
