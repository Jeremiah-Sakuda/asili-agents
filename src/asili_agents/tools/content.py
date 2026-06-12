"""Content tools for channel-fit formatting guidance.

The Content Agent writes captions, product descriptions, and listing copy. The
*copy itself* is the LLM's creative work, but the FORMATTING CONSTRAINTS per
channel (length budgets, hashtag norms, CTA style) are deterministic facts the
agent must respect — so they live here as a plain, unit-testable function rather
than in the prompt where the model could drift on them.

This keeps the same discipline the catalog/pricing tools use: facts the agent
must not invent are returned by a tool, not recalled from memory.
"""

from typing import Any

# Per-channel formatting specs. Conservative, platform-true norms as of 2026:
# the goal is on-platform-correct copy (a caption that fits IG, a description
# that reads as a marketplace listing), not maximums that would read as spam.
_CHANNEL_SPECS: dict[str, dict[str, Any]] = {
    "instagram": {
        "channel": "instagram",
        "format": "caption",
        "max_chars": 2200,
        "ideal_chars": 220,
        "hashtags": "3-8 specific, niche hashtags at the end (not 30 generic ones)",
        "emoji": "sparing — one or two that fit the brand, never decorative walls",
        "cta": "soft CTA — 'DM to order', 'comment your size', 'link in bio'",
        "tone_note": "lead with the hook in the first line; the rest is truncated in-feed",
    },
    "tiktok": {
        "channel": "tiktok",
        "format": "caption",
        "max_chars": 2200,
        "ideal_chars": 150,
        "hashtags": "2-5 trend-aware hashtags; favor discovery over branding",
        "emoji": "playful, native to the platform; still brand-appropriate",
        "cta": "punchy CTA tied to the video — 'watch till the end', 'DM to grab one'",
        "tone_note": "front-load energy; the caption supports the video, it doesn't carry it",
    },
    "facebook": {
        "channel": "facebook",
        "format": "post",
        "max_chars": 5000,
        "ideal_chars": 400,
        "hashtags": "0-2 hashtags; Facebook readers skim, hashtags add little",
        "emoji": "minimal; a warmer, slightly longer narrative voice works here",
        "cta": "clear CTA with the next step — 'message us to reserve', 'comment SOLD'",
        "tone_note": "more room for story and context than IG/TikTok; still get to the point",
    },
    "listing": {
        "channel": "listing",
        "format": "product_description",
        "max_chars": 1200,
        "ideal_chars": 500,
        "hashtags": "none — this is a product description, not a social post",
        "emoji": "none",
        "cta": "none — describe the product; the marketplace UI carries the buy action",
        "tone_note": "lead with what it is, then materials/size/origin, then care/shipping",
    },
}

# Aliases so the agent (or a routed request) can name channels naturally.
_ALIASES: dict[str, str] = {
    "ig": "instagram",
    "insta": "instagram",
    "instagram dm": "instagram",
    "reels": "instagram",
    "fb": "facebook",
    "meta": "facebook",
    "tik tok": "tiktok",
    "product": "listing",
    "description": "listing",
    "shop": "listing",
}


def channel_format_spec(channel: str) -> dict[str, Any]:
    """Return the formatting constraints for a content channel.

    Use this BEFORE writing any caption, post, or listing so the copy fits the
    channel it's for. The returned spec is the source of truth for length,
    hashtag, emoji, and CTA norms — follow it rather than guessing.

    Args:
        channel: Target channel — "instagram", "tiktok", "facebook", or
            "listing" (product description). Common aliases ("ig", "fb",
            "reels", "product") are accepted.

    Returns:
        A dict with the channel's format, char budgets, and style guidance. For
        an unknown channel, returns the Instagram spec with ``matched=False`` so
        the caller can see the fallback was used.

    Example:
        >>> channel_format_spec("ig")
        {"channel": "instagram", "max_chars": 2200, "matched": True, ...}
    """
    key = channel.strip().lower()
    key = _ALIASES.get(key, key)
    spec = _CHANNEL_SPECS.get(key)
    if spec is None:
        # Unknown channel: fall back to Instagram (the wedge channel) but flag it
        # so the agent can note the assumption rather than silently mis-format.
        return {**_CHANNEL_SPECS["instagram"], "matched": False, "requested": channel}
    return {**spec, "matched": True}
