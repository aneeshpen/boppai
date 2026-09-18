"""Port of backend/test/calendar.test.js.

Same cases, same expected values -- these assertions are the contract the frontend
and the conductor both depend on.
"""

from __future__ import annotations

import pytest

from app.services import calendar


def test_writes_reads_and_normalizes_a_session_calendar(session):
    saved = calendar.write(
        session,
        {
            "ignored": True,
            "weeks": [
                {
                    "id": "week-1",
                    "title": "Week 1",
                    "startDate": "Aug 3",
                    "endDate": "Aug 9",
                    "extra": "drop me",
                    "days": [
                        {
                            "day": "Monday",
                            # a numeric calories value is coerced to a string
                            "breakfast": {"name": "Paneer sandwich", "calories": 500},
                            "lunch": None,
                            "dinner": {"name": "Chicken rice bowl"},
                            "extra": "drop me",
                        }
                    ],
                }
            ],
        },
    )

    assert saved == {
        "ui": {"selectedWeekId": "week-1"},
        "weeks": [
            {
                "id": "week-1",
                "title": "Week 1",
                "startDate": "Aug 3",
                "endDate": "Aug 9",
                "days": [
                    {
                        "day": "Monday",
                        "disabled": False,
                        "breakfast": {"name": "Paneer sandwich", "calories": "500"},
                        "dinner": {"name": "Chicken rice bowl"},
                    }
                ],
            }
        ],
    }

    assert calendar.read(session) == (True, saved)


def test_clear_day_disables_the_day_and_removes_meal_slots(session):
    calendar.write(
        session,
        {
            "weeks": [
                {
                    "id": "week-1",
                    "title": "Week 1",
                    "startDate": "Aug 3",
                    "endDate": "Aug 9",
                    "days": [
                        {
                            "day": "Friday",
                            "breakfast": {"name": "Oats"},
                            "lunch": {"name": "Dal rice"},
                            "dinner": {"name": "Fish curry"},
                        }
                    ],
                }
            ]
        },
    )

    updated = calendar.clear_day(session, "week-1", "Friday")
    assert updated["weeks"][0]["days"][0] == {"day": "Friday", "disabled": True}
    assert updated["ui"] == {"selectedWeekId": "week-1"}


def test_select_week_stores_the_visible_week_in_ui_state(session):
    calendar.write(
        session,
        {
            "weeks": [
                {
                    "id": "week-1",
                    "title": "Week 1",
                    "startDate": "Aug 3",
                    "endDate": "Aug 9",
                    "days": [],
                },
                {
                    "id": "week-2",
                    "title": "Week 2",
                    "startDate": "Aug 10",
                    "endDate": "Aug 16",
                    "days": [],
                },
            ]
        },
    )

    updated = calendar.select_week(session, "week-2")
    assert updated["ui"]["selectedWeekId"] == "week-2"
    _, stored = calendar.read(session)
    assert stored["ui"]["selectedWeekId"] == "week-2"


def test_normalizes_youtube_videos_and_drops_them_with_stale_meal_details(session):
    saved = calendar.write(
        session,
        {
            "weeks": [
                {
                    "id": "week-1",
                    "title": "Week 1",
                    "startDate": "Aug 3",
                    "endDate": "Aug 9",
                    "days": [
                        {
                            "day": "Monday",
                            "lunch": {
                                "name": "Paneer biryani",
                                "ingredients": [{"name": "Paneer", "quantity": "200 g"}],
                                "nutrition": {"protein": "24 g"},
                                "youtubeVideos": [
                                    {
                                        "title": "Paneer biryani",
                                        "url": "https://www.youtube.com/watch?v=abcdefghijk",
                                    },
                                    {
                                        "title": "Search results",
                                        "url": "https://www.youtube.com/results?search_query=paneer+biryani",
                                    },
                                ],
                            },
                        }
                    ],
                }
            ]
        },
    )

    # the non-video /results link is dropped
    assert saved["weeks"][0]["days"][0]["lunch"]["youtubeVideos"] == [
        {"title": "Paneer biryani", "url": "https://www.youtube.com/watch?v=abcdefghijk"}
    ]

    # renaming the dish invalidates every cached detail for that slot
    updated = calendar.write(
        session,
        {
            "weeks": [
                {
                    "id": "week-1",
                    "title": "Week 1",
                    "startDate": "Aug 3",
                    "endDate": "Aug 9",
                    "days": [
                        {
                            "day": "Monday",
                            "lunch": {
                                "name": "Veg biryani",
                                "ingredients": [{"name": "Paneer", "quantity": "200 g"}],
                                "nutrition": {"protein": "24 g"},
                                "youtubeVideos": [
                                    {
                                        "title": "Paneer biryani",
                                        "url": "https://youtu.be/abcdefghijk",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ]
        },
    )

    assert updated["weeks"][0]["days"][0]["lunch"] == {"name": "Veg biryani"}


# --- extra coverage for rules the Node suite exercised only indirectly ---


def test_servings_is_only_stored_above_one(session):
    saved = calendar.write(
        session,
        {
            "weeks": [
                {
                    "id": "w",
                    "title": "W",
                    "startDate": "a",
                    "endDate": "b",
                    "days": [
                        {
                            "day": "Monday",
                            "breakfast": {"name": "Oats", "servings": 1},
                            "lunch": {"name": "Biryani", "servings": 2},
                        }
                    ],
                }
            ]
        },
    )
    day = saved["weeks"][0]["days"][0]
    assert "servings" not in day["breakfast"]
    assert day["lunch"]["servings"] == 2


def test_changing_servings_also_invalidates_cached_details(session):
    base_day = {
        "day": "Monday",
        "lunch": {
            "name": "Biryani",
            "servings": 2,
            "ingredients": [{"name": "Rice", "quantity": "2 cups"}],
        },
    }
    week = {"id": "w", "title": "W", "startDate": "a", "endDate": "b", "days": [base_day]}
    calendar.write(session, {"weeks": [week]})

    bumped = {**base_day, "lunch": {**base_day["lunch"], "servings": 4}}
    updated = calendar.write(
        session, {"weeks": [{**week, "days": [bumped]}]}
    )
    assert "ingredients" not in updated["weeks"][0]["days"][0]["lunch"]


def test_selected_week_id_falls_back_to_the_first_week(session):
    saved = calendar.write(
        session,
        {
            "ui": {"selectedWeekId": "does-not-exist"},
            "weeks": [
                {"id": "w1", "title": "W1", "startDate": "a", "endDate": "b", "days": []},
                {"id": "w2", "title": "W2", "startDate": "c", "endDate": "d", "days": []},
            ],
        },
    )
    assert saved["ui"]["selectedWeekId"] == "w1"


def test_rejects_an_unknown_weekday(session):
    with pytest.raises(ValueError, match="Invalid day"):
        calendar.write(
            session,
            {
                "weeks": [
                    {
                        "id": "w",
                        "title": "W",
                        "startDate": "a",
                        "endDate": "b",
                        "days": [{"day": "Caturday"}],
                    }
                ]
            },
        )


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=abcdefghijk", True),
        ("https://youtu.be/abcdefghijk", True),
        ("https://m.youtube.com/watch?v=abcdefghijk", True),
        ("https://www.youtube.com/shorts/abcdefghijk", True),
        ("https://www.youtube-nocookie.com/embed/abcdefghijk", True),
        ("https://www.youtube.com/results?search_query=paneer", False),
        ("https://vimeo.com/abcdefghijk", False),
        ("not a url", False),
        ("", False),
    ],
)
def test_youtube_url_recognition(url, expected):
    assert calendar.is_youtube_video_url(url) is expected
