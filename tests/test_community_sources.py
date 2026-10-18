"""Community access boundaries, evidence provenance, parsing and honest failures."""
import copy
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import community_sources as community


NOW = datetime(2026, 10, 18, 5, tzinfo=timezone.utc)
CHANNEL = "123456789012345678"
OTHER_CHANNEL = "223456789012345678"
GUILD = "323456789012345678"
MESSAGE = "423456789012345678"
REDDIT = {"id": "reddit_gamedesign", "name": "r/gamedesign", "url": "https://www.reddit.com/r/gamedesign/",
          "platform": "reddit", "adapter": "reddit_oauth", "subreddit": "gamedesign", "tier": 3,
          "lang": "en", "category": "design", "window_hours": 168, "max_per_source": 20,
          "publication_scope": "public"}
DISCORD = {"id": "discord_unity", "name": "Unity 官方 Discord", "url": "https://discord.com/invite/unity",
           "platform": "discord", "adapter": "discord_bot", "tier": 3, "lang": "en", "category": "development",
           "window_hours": 72, "max_per_source": 20, "channel_ids": [], "publication_scope": "restricted"}


def response(payload=None, code=200, headers=None):
    result = Mock(status_code=code, headers=headers or {})
    result.json.return_value = payload
    return result


def post(**changes):
    data = {"title": "How should attack recovery work?", "permalink": "/r/gamedesign/comments/abc123/attack_recovery/",
            "created_utc": (NOW - timedelta(hours=3)).timestamp(), "is_self": True,
            "selftext": "Our prototype has two cancel windows. We have not tested either one yet.",
            "url": "https://www.reddit.com/r/gamedesign/comments/abc123/attack_recovery/",
            "link_flair_text": "Question", "score": 91, "num_comments": 8}
    data.update(changes)
    return {"kind": "t3", "data": data}


def listing(*posts):
    return {"kind": "Listing", "data": {"children": list(posts)}}


def channel_meta(channel_id=CHANNEL, **changes):
    return dict({"id": channel_id, "guild_id": GUILD, "type": 0}, **changes)


def message(**changes):
    data = {"id": MESSAGE, "channel_id": CHANNEL, "type": 0, "timestamp": "2026-10-18T01:30:00Z",
            "content": "# Animation testing notes\nSee <https://example.com/design> <@123456789012345678>",
            "embeds": [], "attachments": []}
    data.update(changes)
    return data


class CommunitySourceTests(unittest.TestCase):
    def run_fetch(self, sources, env=None, replies=None):
        with patch.object(community, "load_catalog", return_value=copy.deepcopy(sources)), \
             patch.dict(os.environ, env or {}, clear=True), \
             patch.object(community.requests, "get", side_effect=replies) as get:
            articles, statuses = community.fetch_sources(NOW)
        return articles, statuses, get

    def test_catalog_registers_three_reddit_and_three_discord_sources(self):
        sources = community.load_catalog()
        self.assertEqual({source["subreddit"] for source in sources if source["platform"] == "reddit"},
                         {"gamedesign", "gamedev", "leveldesign"})
        discord = [source for source in sources if source["platform"] == "discord"]
        self.assertEqual(len(discord), 3)
        self.assertTrue(all(not source["channel_ids"] and source["publication_scope"] == "restricted" for source in discord))

    def test_no_credentials_does_not_attempt_anonymous_or_personal_access(self):
        articles, statuses, get = self.run_fetch([REDDIT, DISCORD])
        self.assertEqual(articles, [])
        self.assertEqual([entry["state"] for entry in statuses], ["needs_auth", "needs_auth"])
        get.assert_not_called()

    def test_empty_optional_ci_environment_uses_no_allowlist_and_default_user_agent(self):
        env = {"REDDIT_ACCESS_TOKEN": "approved", "REDDIT_USER_AGENT": "", "DISCORD_BOT_TOKEN": "", "DISCORD_CHANNELS_JSON": ""}
        _, statuses, get = self.run_fetch([REDDIT, DISCORD], env, [response(listing(post()))])
        self.assertEqual([entry["state"] for entry in statuses], ["ok", "needs_auth"])
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs["headers"]["User-Agent"], community.USER_AGENT)

    def test_reddit_selftext_remains_reviewable_community_evidence(self):
        articles, statuses, get = self.run_fetch([REDDIT], {"REDDIT_ACCESS_TOKEN": "approved-token"}, [response(listing(post()))])
        self.assertEqual(statuses[0]["state"], "ok")
        item = articles[0]
        self.assertTrue(item["is_question"] and item["requires_review"])
        self.assertEqual(item["evidence_kind"], "community_post")
        self.assertEqual(item["content_kind"], "community_selftext")
        self.assertEqual(item["pool"], "community")
        self.assertFalse(item["has_body"])
        self.assertIn("not tested", item["rss_content"])
        self.assertEqual(item["signals"]["rank_bonus"], 0)
        self.assertEqual(item["signals"]["reddit_score"], 91)
        self.assertEqual(item["url"], item["discovery_url"])
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer approved-token")
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertNotIn("author", item)

    def test_reddit_link_keeps_external_original_separate_from_discussion(self):
        linked = post(is_self=False, selftext="", url="https://example.com/postmortem", title="A combat postmortem", link_flair_text="Resource")
        item = community.parse_reddit_listing(listing(linked), REDDIT, NOW)[0]
        self.assertEqual(item["evidence_kind"], "community_link")
        self.assertEqual(item["original_url"], "https://example.com/postmortem")
        self.assertIn("reddit.com/r/gamedesign/comments/", item["url"])
        self.assertFalse(item["is_question"])

    def test_removed_old_future_and_wrong_subreddit_are_not_returned(self):
        payload = listing(post(selftext="[removed]"), post(removed_by_category="moderator"),
                          post(created_utc=(NOW - timedelta(days=9)).timestamp()),
                          post(created_utc=(NOW + timedelta(days=1)).timestamp()),
                          post(permalink="/r/other/comments/abc123/title/"), post(over_18=True))
        self.assertEqual(community.parse_reddit_listing(payload, REDDIT, NOW), [])

    def test_missing_date_is_not_invented(self):
        item = community.parse_reddit_listing(listing(post(created_utc=None)), REDDIT, NOW)[0]
        self.assertIsNone(item["published"])
        self.assertTrue(item["undated"])

    def test_401_403_and_429_are_distinct_explicit_failures(self):
        for code, state in [(401, "needs_auth"), (403, "needs_auth"), (429, "error")]:
            with self.subTest(code=code):
                items, statuses, get = self.run_fetch([REDDIT], {"REDDIT_ACCESS_TOKEN": "approved"}, [response(code=code, headers={"Retry-After": "60"})])
                self.assertEqual(items, [])
                self.assertEqual(statuses[0]["state"], state)
                self.assertEqual(statuses[0]["http_status"], code)
                self.assertIn(str(code), statuses[0]["detail"])

    def test_rate_limit_stops_subsequent_platform_calls(self):
        second = dict(REDDIT, id="reddit_gamedev", name="r/gamedev", subreddit="gamedev")
        _, statuses, get = self.run_fetch([REDDIT, second], {"REDDIT_ACCESS_TOKEN": "approved"}, [response(code=429)])
        self.assertEqual(get.call_count, 1)
        self.assertEqual([entry["http_status"] for entry in statuses], [429, 429])

    def test_malformed_reddit_data_is_status_not_uncaught_crash(self):
        _, statuses, _ = self.run_fetch([REDDIT], {"REDDIT_ACCESS_TOKEN": "approved"}, [response({"data": None})])
        self.assertEqual(statuses[0]["state"], "error")

    def test_discord_bot_without_explicit_channel_never_requests_history(self):
        _, statuses, get = self.run_fetch([DISCORD], {"DISCORD_BOT_TOKEN": "bot-token"})
        self.assertEqual(statuses[0]["state"], "needs_auth")
        get.assert_not_called()

    def test_discord_env_allowlist_overrides_source_channels_and_keeps_restricted(self):
        configured = dict(DISCORD, channel_ids=[OTHER_CHANNEL])
        env = {"DISCORD_BOT_TOKEN": "bot-token", "DISCORD_CHANNELS_JSON": '{"discord_unity":["' + CHANNEL + '"]}'}
        items, statuses, get = self.run_fetch([configured], env, [response(channel_meta()), response([message()])])
        self.assertEqual(statuses[0]["state"], "ok")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["publication_scope"], "restricted")
        self.assertTrue(items[0]["requires_review"])
        self.assertFalse(items[0]["has_body"])
        self.assertEqual(items[0]["original_url"], "https://example.com/design")
        self.assertNotIn("<@", items[0]["rss_content"])
        self.assertEqual(items[0]["discovery_url"], f"https://discord.com/channels/{GUILD}/{CHANNEL}/{MESSAGE}")
        self.assertEqual(items[0]["published"], "2026-10-18T01:30:00+00:00")
        self.assertEqual([call.args[0] for call in get.call_args_list],
                         [f"{community.DISCORD_API}/channels/{CHANNEL}", f"{community.DISCORD_API}/channels/{CHANNEL}/messages"])
        self.assertTrue(all(call.kwargs["headers"]["Authorization"] == "Bot bot-token" for call in get.call_args_list))

    def test_discord_publication_requires_both_explicit_signals_and_still_review(self):
        channel = {"channel_id": CHANNEL}
        public_source = dict(DISCORD, publication_scope="public")
        self.assertEqual(community._public_scope(public_source, channel), "restricted")
        channel.update(publication_scope="public", public_publication_authorized=True)
        item = community.parse_discord_messages([message()], DISCORD, channel, GUILD, NOW)[0]
        self.assertEqual(item["publication_scope"], "public")
        self.assertTrue(item["requires_review"])

    def test_discord_missing_message_content_is_needs_auth_not_false_success(self):
        source = dict(DISCORD, channel_ids=[CHANNEL])
        _, statuses, _ = self.run_fetch([source], {"DISCORD_BOT_TOKEN": "bot"},
                                       [response(channel_meta()), response([message(content="", embeds=[], attachments=[])])])
        self.assertEqual(statuses[0]["state"], "needs_auth")
        self.assertIn("MESSAGE_CONTENT", statuses[0]["channels"][0]["detail"])

    def test_attachment_only_message_is_empty_not_assumed_permission_failure(self):
        result = community.parse_discord_messages([message(content="", attachments=[{"filename": "image.png"}])],
                                                  DISCORD, {"channel_id": CHANNEL}, GUILD, NOW)
        self.assertEqual(result, [])

    def test_forum_requires_specific_thread_and_dms_are_not_read(self):
        source = dict(DISCORD, channel_ids=[CHANNEL])
        for meta, state in [(channel_meta(type=15), "manual"), ({"id": CHANNEL, "type": 1}, "needs_auth")]:
            with self.subTest(type=meta["type"]):
                _, statuses, get = self.run_fetch([source], {"DISCORD_BOT_TOKEN": "bot"}, [response(meta)])
                self.assertEqual(statuses[0]["state"], state)
                self.assertEqual(get.call_count, 1)

    def test_malformed_or_unknown_allowlist_never_makes_requests(self):
        for raw in ["not json", '["' + CHANNEL + '"]', '{"discord_unity":"../private"}', '{"unregistered":"' + CHANNEL + '"}']:
            with self.subTest(raw=raw):
                _, statuses, get = self.run_fetch([DISCORD], {"DISCORD_BOT_TOKEN": "bot", "DISCORD_CHANNELS_JSON": raw})
                self.assertEqual(statuses[0]["state"], "error")
                get.assert_not_called()

    def test_discord_http_forbidden_is_reported_per_channel(self):
        source = dict(DISCORD, channel_ids=[CHANNEL])
        _, statuses, _ = self.run_fetch([source], {"DISCORD_BOT_TOKEN": "bot"}, [response(code=403)])
        self.assertEqual(statuses[0]["state"], "needs_auth")
        self.assertEqual(statuses[0]["channels"][0]["http_status"], 403)

    def test_discord_429_halts_other_channels_and_sources(self):
        first = dict(DISCORD, channel_ids=[CHANNEL, OTHER_CHANNEL])
        second = dict(DISCORD, id="discord_godot", channel_ids=[OTHER_CHANNEL])
        _, statuses, get = self.run_fetch([first, second], {"DISCORD_BOT_TOKEN": "bot"},
                                          [response(channel_meta()), response(code=429)])
        self.assertEqual(get.call_count, 2)
        self.assertEqual([entry["state"] for entry in statuses], ["error", "error"])
        self.assertIn("429", statuses[0]["detail"])
        self.assertEqual(statuses[1]["http_status"], 429)

    def test_discord_maximum_and_duplicate_messages_are_bounded(self):
        source = dict(DISCORD, max_per_source=1, channel_ids=[CHANNEL])
        second = message(id="523456789012345678")
        items, statuses, _ = self.run_fetch([source], {"DISCORD_BOT_TOKEN": "bot"},
                                           [response(channel_meta()), response([message(), message(), second])])
        self.assertEqual(len(items), 1)
        self.assertEqual(statuses[0]["count"], 1)
        self.assertEqual(statuses[0]["channels"][0]["count"], 1)

    def test_network_and_invalid_json_fail_without_secret_in_details(self):
        invalid = response()
        invalid.json.side_effect = ValueError("private-response-body")
        for reply in [community.requests.Timeout("secret-token"), invalid]:
            with self.subTest(reply=type(reply).__name__):
                _, statuses, _ = self.run_fetch([REDDIT], {"REDDIT_ACCESS_TOKEN": "secret-token"}, [reply])
                self.assertEqual(statuses[0]["state"], "error")
                self.assertNotIn("secret-token", statuses[0]["detail"])
                self.assertNotIn("private-response-body", statuses[0]["detail"])


if __name__ == "__main__":
    unittest.main()
