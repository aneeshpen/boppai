"""Port of backend/test/ingredients.test.js, plus the batching rules it relies on."""

from __future__ import annotations

from app.services.ingredients import fan_out, group_by_dish, pending_for_day, shape_entry


def test_pending_for_day_force_includes_named_meals_even_when_cached():
    day = {
        "day": "Monday",
        "breakfast": {"name": "Oats", "ingredients": [{"name": "Oats", "quantity": "1 cup"}]},
        "lunch": {"name": "Chicken rice bowl", "ingredients": []},
        "dinner": None,
    }

    assert pending_for_day(day) == []
    assert pending_for_day(day, force=True) == [
        {"meal": "breakfast", "name": "Oats", "servings": 1},
        {"meal": "lunch", "name": "Chicken rice bowl", "servings": 1},
    ]


def test_a_shared_dish_regenerates_as_a_whole_group():
    # Lunch already has ingredients but dinner (same dish) does not, so BOTH slots
    # come back -- otherwise the two cards would show inconsistent batch lists.
    day = {
        "lunch": {"name": "Biryani", "servings": 2, "ingredients": [{"name": "Rice"}]},
        "dinner": {"name": "Biryani", "servings": 2},
    }
    assert [p["meal"] for p in pending_for_day(day)] == ["lunch", "dinner"]


def test_unrelated_generated_meals_are_left_alone():
    day = {
        "breakfast": {"name": "Oats", "ingredients": [{"name": "Oats"}]},
        "lunch": {"name": "Dal"},
    }
    assert [p["meal"] for p in pending_for_day(day)] == ["lunch"]


def test_group_by_dish_takes_batch_size_once_not_summed():
    grouped = group_by_dish(
        [
            {"meal": "lunch", "name": "Biryani", "servings": 2},
            {"meal": "dinner", "name": "Biryani", "servings": 1},
        ]
    )
    assert grouped == [{"name": "Biryani", "servings": 2, "mealKeys": ["lunch", "dinner"]}]


def test_fan_out_writes_one_batch_list_to_every_shared_slot():
    dishes = [{"name": "Biryani", "servings": 2, "mealKeys": ["lunch", "dinner"]}]
    parsed = {"Biryani": {"ingredients": [{"name": "Rice", "quantity": "2 cups"}]}}
    out = fan_out(dishes, parsed)
    assert out["lunch"] == out["dinner"]
    assert out["lunch"]["ingredients"] == [{"name": "Rice", "quantity": "2 cups"}]


def test_shape_entry_drops_non_youtube_links_and_nameless_ingredients():
    shaped = shape_entry(
        {
            "ingredients": [{"name": "  Onion ", "quantity": "2"}, {"name": "   "}, {}],
            "nutrition": {"protein": "12 g"},
            "youtubeVideos": [
                {"title": "ok", "url": "https://www.youtube.com/watch?v=abcdefghijk"},
                {"title": "bad", "url": "https://example.com/video"},
            ],
        }
    )
    assert shaped["ingredients"] == [{"name": "Onion", "quantity": "2"}]
    assert shaped["nutrition"] == {"protein": "12 g", "carbs": "", "fat": "", "fiber": ""}
    assert [v["url"] for v in shaped["youtubeVideos"]] == [
        "https://www.youtube.com/watch?v=abcdefghijk"
    ]


def test_shape_entry_tolerates_garbage():
    assert shape_entry(None) == {"ingredients": [], "nutrition": None, "youtubeVideos": []}
    assert shape_entry({"ingredients": "nope"})["ingredients"] == []


def test_fan_out_tolerates_the_model_echoing_the_batch_suffix_in_keys():
    """Regression for a latent bug carried over from the Node build.

    The prompt lists dishes as "- Oats (cook a batch of 1 serving)" and asks for keys
    "EXACTLY as written above". The model sometimes returns the bare dish name and
    sometimes the whole bullet. A strict lookup misses the latter and the day's card
    renders empty.
    """
    dishes = [
        {"name": "Oats", "servings": 1, "mealKeys": ["breakfast"]},
        {"name": "Paneer Biryani", "servings": 2, "mealKeys": ["lunch", "dinner"]},
    ]
    parsed = {
        "Oats (cook a batch of 1 serving)": {
            "ingredients": [{"name": "Rolled oats", "quantity": "40 g"}]
        },
        "Paneer Biryani (cook a batch of 2 servings)": {
            "ingredients": [{"name": "Paneer", "quantity": "200 g"}]
        },
    }

    out = fan_out(dishes, parsed)
    assert [i["name"] for i in out["breakfast"]["ingredients"]] == ["Rolled oats"]
    assert [i["name"] for i in out["lunch"]["ingredients"]] == ["Paneer"]
    assert out["lunch"] == out["dinner"]


def test_fan_out_still_prefers_an_exact_key_match():
    dishes = [{"name": "Oats", "servings": 1, "mealKeys": ["breakfast"]}]
    parsed = {
        "Oats": {"ingredients": [{"name": "Exact"}]},
        "Oats (cook a batch of 1 serving)": {"ingredients": [{"name": "Suffixed"}]},
    }
    assert fan_out(dishes, parsed)["breakfast"]["ingredients"][0]["name"] == "Exact"


def test_fan_out_is_case_insensitive_on_the_dish_name():
    dishes = [{"name": "Paneer Biryani", "servings": 2, "mealKeys": ["lunch"]}]
    parsed = {"paneer biryani (cook a batch of 2 servings)": {"ingredients": [{"name": "Rice"}]}}
    assert fan_out(dishes, parsed)["lunch"]["ingredients"][0]["name"] == "Rice"


def test_fan_out_returns_empty_when_the_dish_is_genuinely_absent():
    dishes = [{"name": "Oats", "servings": 1, "mealKeys": ["breakfast"]}]
    assert fan_out(dishes, {"Something Else": {"ingredients": [{"name": "x"}]}})["breakfast"][
        "ingredients"
    ] == []
