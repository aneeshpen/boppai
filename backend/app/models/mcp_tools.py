"""
Pydantic schemas for the Boppai MCP tools -- the Zod models from the Node build.

Two rules govern this file:

1. Field names stay camelCase (`packSize`, `imageUrl`, `selectedWeekId`). They are the
   JSON the agent emits and the frontend reads, so they are the contract, not a style
   choice.
2. Every `description` is copied VERBATIM from the Zod `.describe()` calls. These
   strings are not documentation -- they are the instructions the agent reads to decide
   what to put in each field, so paraphrasing them changes product behavior.

`z.nullish()` (null OR omitted) maps to `X | None = None`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DayName = Literal[
    "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"
]
MerchantOutcome = Literal["APPROVED", "DECLINED"]


class _Model(BaseModel):
    # The agent sometimes emits extra keys; the Node normalizers dropped them silently
    # rather than failing the tool call, so do the same here.
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Meal(_Model):
    name: str = Field(min_length=1, description="The visible meal name.")
    calories: str | None = Field(
        default=None,
        min_length=1,
        description=(
            'Approximate calories for one serving as a short string, e.g. "~450 kcal". '
            "Always include this."
        ),
    )
    servings: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Batch size: how many portions this dish is cooked as. Default 1. Go higher "
            "either when the dish cannot be cooked as a single serving (e.g. biryani, "
            "bakes, roasts, big-batch curries) or when the user wants to eat it more "
            "than once. When a batch feeds more than one slot, put the SAME dish name "
            "in each slot AND set the SAME servings number on each - it is treated as "
            "one cooked batch (its ingredients are generated once for this many "
            "portions), not double-counted."
        ),
    )


class BasketProduct(_Model):
    """One chosen grocery product for a Basket line.

    All fields but `name` are optional because a live search may not return every
    detail -- we keep whatever we get.
    """

    name: str = Field(
        min_length=1,
        description=(
            "The exact product/pack name as listed on the grocery service, e.g. "
            '"India Gate Basmati Rice 1 kg".'
        ),
    )
    packSize: str | None = Field(
        default=None, description='The pack/unit size, e.g. "1 kg", "500 g", "6 pcs".'
    )
    price: str | None = Field(
        default=None, description='The pack price as a short display string, e.g. "₹120".'
    )
    rating: str | None = Field(
        default=None,
        description='The product rating as a short string if shown, e.g. "4.4". Include when available.',
    )
    imageUrl: str | None = Field(
        default=None,
        description=(
            "The product image URL if available. Include when the service returns one; "
            "omit otherwise."
        ),
    )
    productId: str | None = Field(
        default=None,
        description="The service product/variant id if available, kept for later ordering.",
    )


class BasketItem(_Model):
    """One Basket line: the ingredient it fulfills, whether a product was found, and
    (when found) the chosen product plus how many packs to buy."""

    ingredient: str = Field(
        min_length=1,
        description=(
            "The ingredient this line fulfills, spelled EXACTLY as in the shopping list "
            '(e.g. "Tomato"). The app matches cards to the list by this name.'
        ),
    )
    quantity: str | None = Field(
        default=None,
        description=(
            'How much of this ingredient the plan needs, e.g. "2 kg". Copy it from the '
            "shopping list."
        ),
    )
    status: Literal["found", "not_found"] = Field(
        description=(
            '"found" when a suitable product was located, "not_found" when nothing '
            "suitable exists on the service."
        )
    )
    count: int | None = Field(
        default=None,
        ge=1,
        description=(
            "How many packs of the chosen product to buy so pack size x count covers the "
            'needed quantity. Default 1. Only meaningful when status is "found".'
        ),
    )
    product: BasketProduct | None = Field(
        default=None,
        description='The chosen product. REQUIRED when status is "found"; omit when "not_found".',
    )


class PravaProduct(_Model):
    description: str = Field(
        min_length=1,
        description='Product or cart-line description, e.g. "Maggi 2-Minute Noodles".',
    )
    unitPrice: str | None = Field(
        default=None,
        min_length=1,
        description='Line unit price as a decimal string in INR, e.g. "14.00".',
    )
    quantity: int | None = Field(
        default=None, ge=1, description="Quantity for this product line. Default 1."
    )
    productId: str | None = Field(
        default=None, description="Swiggy product/variant id when available."
    )


class Day(_Model):
    day: DayName
    date: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description=(
            "This day's real calendar date as ISO YYYY-MM-DD (e.g. \"2026-06-13\"). Must "
            "match `day` (the weekday name). The card shows it as a short date. Always "
            "include it."
        ),
    )
    breakfast: Meal | None = Field(
        default=None, description="Breakfast meal, or null/omitted when empty."
    )
    lunch: Meal | None = Field(default=None, description="Lunch meal, or null/omitted when empty.")
    dinner: Meal | None = Field(
        default=None, description="Dinner meal, or null/omitted when empty."
    )
    disabled: bool | None = Field(
        default=None, description="True when no meal plan should be shown for this day."
    )


class Week(_Model):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    startDate: str = Field(min_length=1)
    endDate: str = Field(min_length=1)
    days: list[Day] = Field(
        description="The available planned days for this week. Partial final weeks are allowed."
    )


class CalendarUi(_Model):
    selectedWeekId: str | None = Field(
        default=None,
        min_length=1,
        description="The week id that should be visible in the calendar UI.",
    )
