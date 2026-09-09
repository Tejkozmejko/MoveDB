# -*- coding: utf-8 -*-
"""Discount and loyalty programmes for the restaurant POS (rollout task 4.8).

These mirror the three programmes that were configured by hand in the live
database on 7 September, so that a fresh install or a rebuilt database comes up
with the same offers instead of an empty Loyalty menu. ``Gift Cards`` is not
included - that one is created by Odoo itself when ``loyalty`` is installed.

One deliberate difference from the live records: the Happy Hour reward is
scoped to the drinks POS categories. Live, it is set to "specific products"
with an empty product list, which means it currently discounts nothing.
"""

# POS categories whose products count as "drinks" for Happy Hour.
DRINK_POS_CATEGORIES = ["Soft Drinks", "Hot Drinks", "Beer & Wine"]

# Programme currency. Menu prices and the loyalty reward value were set in
# euro; the hook falls back to the company currency if EUR is not active.
PROGRAM_CURRENCY = "EUR"

PROGRAMS = [
    {
        "name": "Happy Hour - Drinks 20% off",
        "program": {
            "program_type": "promotion",
            "applies_on": "current",
            "trigger": "auto",
            "portal_visible": False,
            "pos_ok": True,
            "sale_ok": False,
            "date_from": "2026-09-07",
            "date_to": "2026-12-31",
        },
        "rule": {
            "mode": "auto",
            "minimum_qty": 1,
            "minimum_amount": 0.0,
            "reward_point_amount": 1.0,
            "reward_point_mode": "order",
        },
        "reward": {
            "reward_type": "discount",
            "description": "20% off drinks",
            "discount": 20.0,
            "discount_mode": "percent",
            "discount_applicability": "specific",
            "required_points": 1.0,
        },
        # Fill reward.discount_product_ids from the drinks categories.
        "reward_products": "drinks",
    },
    {
        "name": "Restaurant Loyalty Points",
        "program": {
            "program_type": "loyalty",
            "applies_on": "both",
            "trigger": "auto",
            "portal_visible": True,
            "portal_point_name": "Points",
            "pos_ok": True,
            "sale_ok": False,
        },
        # One point per unit of currency spent.
        "rule": {
            "mode": "auto",
            "minimum_qty": 1,
            "minimum_amount": 0.0,
            "reward_point_amount": 1.0,
            "reward_point_mode": "money",
        },
        "reward": {
            "reward_type": "discount",
            "description": "10.00 off - 100 points",
            "discount": 10.0,
            "discount_mode": "per_order",
            "discount_applicability": "order",
            "required_points": 100.0,
        },
    },
    {
        "name": "Staff Discount 25%",
        "program": {
            "program_type": "promo_code",
            "applies_on": "current",
            "trigger": "with_code",
            "portal_visible": False,
            "pos_ok": True,
            "sale_ok": False,
        },
        "rule": {
            "mode": "with_code",
            "code": "STAFF25",
            "minimum_qty": 1,
            "minimum_amount": 0.0,
            "reward_point_amount": 1.0,
            "reward_point_mode": "order",
        },
        "reward": {
            "reward_type": "discount",
            "description": "25% off the order - staff",
            "discount": 25.0,
            "discount_mode": "percent",
            "discount_applicability": "order",
            "required_points": 1.0,
        },
    },
]
