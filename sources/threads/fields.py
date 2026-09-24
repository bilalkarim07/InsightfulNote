"""Centralised field selections for Threads API requests.

Verify every field against the current Meta documentation before
modifying this file.
"""

# ---------------------------------------------------------------------------
# Post fields
# ---------------------------------------------------------------------------
POST_FIELDS: list[str] = [
    "id",
    "media_product_type",
    "media_type",
    "permalink",
    "owner",
    "username",
    "text",
    "timestamp",
    "shortcode",
    "thumbnail_url",
    "has_replies",
    "is_quote_post",
]

REPLY_FIELDS: list[str] = [
    "id",
    "text",
    "timestamp",
    "media_product_type",
    "media_type",
    "permalink",
    "shortcode",
    "username",
    "is_reply",
    "is_reply_owned_by_me",
    "root_post",
    "replied_to",
]

PROFILE_FIELDS: list[str] = [
    "id",
    "username",
    "name",
    "biography",
    "profile_picture_url",
    "follower_count",
    "following_count",
    "is_verified",
]

SEARCH_FIELDS: list[str] = [
    "id",
    "text",
    "username",
    "timestamp",
    "permalink",
    "media_type",
    "has_replies",
]


def fields_to_string(fields: list[str] | None) -> str:
    """Convert a list of field names into the comma-separated string
    expected by the Threads API."""
    if not fields:
        return ""
    return ",".join(fields)