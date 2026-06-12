"""Tests for the channel_format_spec content tool.

The copy itself is the LLM's creative work, but the per-channel formatting
constraints are deterministic facts — so they get deterministic tests.
"""

from asili_agents.tools.content import channel_format_spec


class TestChannelFormatSpec:
    def test_known_channels_match(self):
        for channel in ("instagram", "tiktok", "facebook", "listing"):
            spec = channel_format_spec(channel)
            assert spec["matched"] is True
            assert spec["channel"] == channel
            assert spec["max_chars"] > 0
            assert "cta" in spec

    def test_aliases_resolve(self):
        assert channel_format_spec("ig")["channel"] == "instagram"
        assert channel_format_spec("IG")["channel"] == "instagram"
        assert channel_format_spec("fb")["channel"] == "facebook"
        assert channel_format_spec("reels")["channel"] == "instagram"
        assert channel_format_spec("product")["channel"] == "listing"

    def test_whitespace_and_case_tolerant(self):
        assert channel_format_spec("  Instagram  ")["channel"] == "instagram"
        assert channel_format_spec("Instagram DM")["channel"] == "instagram"

    def test_unknown_channel_falls_back_flagged(self):
        spec = channel_format_spec("carrier-pigeon")
        # Falls back to the wedge channel but flags that it didn't match, so the
        # agent can surface the assumption instead of silently mis-formatting.
        assert spec["matched"] is False
        assert spec["channel"] == "instagram"
        assert spec["requested"] == "carrier-pigeon"

    def test_listing_has_no_hashtags_or_emoji(self):
        spec = channel_format_spec("listing")
        assert "none" in spec["hashtags"].lower()
        assert "none" in spec["emoji"].lower()
