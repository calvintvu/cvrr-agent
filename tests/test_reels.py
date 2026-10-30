import unittest

from pydantic import ValidationError

from reels_ripper_agent.reels import Reel, check_output

REEL_URL = "https://www.instagram.com/reel/DS-q1TClQuu/"
SECOND_URL = "https://www.instagram.com/reel/DSeAlkvk1jW/"


class ReelOutputTests(unittest.TestCase):
    def test_reel_output(self) -> None:
        result = check_output([{"url": REEL_URL, "author_username": "theanomalyvault"}])

        self.assertIsInstance(result[0], Reel)
        self.assertEqual(
            result[0].model_dump(),
            {"url": REEL_URL, "author_username": "theanomalyvault"},
        )

    def test_unknown_author(self) -> None:
        result = check_output([{"url": REEL_URL, "author_username": None}])

        self.assertEqual(
            result[0].model_dump(), {"url": REEL_URL, "author_username": None}
        )

    def test_empty_output(self) -> None:
        self.assertEqual(check_output([]), [])

    def test_rejects_non_list_output(self) -> None:
        for raw in [None, {}, "[]", (), ({"url": REEL_URL},)]:
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                check_output(raw)

    def test_requires_both_fields(self) -> None:
        for record in [{}, {"url": REEL_URL}, {"author_username": None}]:
            with self.subTest(record=record), self.assertRaises(ValidationError):
                check_output([record])

    def test_rejects_extra_fields(self) -> None:
        with self.assertRaises(ValidationError):
            check_output(
                [{"url": REEL_URL, "author_username": None, "caption": "hello"}]
            )

    def test_rejects_wrong_field_types(self) -> None:
        for record in [
            {"url": 123, "author_username": None},
            {"url": REEL_URL.encode(), "author_username": None},
            {"url": REEL_URL, "author_username": 123},
            {"url": REEL_URL, "author_username": b"theanomalyvault"},
            {"url": REEL_URL, "author_username": []},
        ]:
            with self.subTest(record=record), self.assertRaises(ValidationError):
                check_output([record])

    def test_rejects_blank_authors(self) -> None:
        for author in ["", "   ", "\n\t"]:
            with self.subTest(author=author), self.assertRaises(ValidationError):
                check_output([{"url": REEL_URL, "author_username": author}])

    def test_excludes_posts(self) -> None:
        result = check_output(
            [
                {
                    "url": "https://www.instagram.com/p/post_123/",
                    "author_username": None,
                },
                {"url": REEL_URL, "author_username": "theanomalyvault"},
            ]
        )

        self.assertEqual([reel.url for reel in result], [REEL_URL])
        self.assertEqual(
            check_output(
                [
                    {
                        "url": "https://www.instagram.com/p/post_123/",
                        "author_username": None,
                    }
                ]
            ),
            [],
        )

    def test_rejects_malformed_or_unexpected_urls(self) -> None:
        for url in [
            "not a URL",
            "www.instagram.com/reel/abc/",
            "https://example.com/reel/abc/",
            "https://instagram.com.evil.example/reel/abc/",
            "https://www.instagram.com@evil.example/reel/abc/",
            "https://user@www.instagram.com/reel/abc/",
            "ftp://www.instagram.com/reel/abc/",
            "https://www.instagram.com/reel/",
            "https://www.instagram.com/reel/abc/extra/",
            "https://www.instagram.com/reel/../",
            "https://www.instagram.com/stories/abc/",
            "https://www.instagram.com/reel/abc/?invalid=\x00",
            f" {REEL_URL}",
            f"{REEL_URL}\n",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                check_output([{"url": url, "author_username": None}])

    def test_deduplicates_shared_url_variants(self) -> None:
        result = check_output(
            [
                {
                    "url": "http://INSTAGRAM.COM/reel/DS-q1TClQuu",
                    "author_username": None,
                },
                {"url": f"{REEL_URL}?igsh=example#fragment", "author_username": None},
                {"url": REEL_URL, "author_username": None},
            ]
        )

        self.assertEqual([reel.url for reel in result], [REEL_URL])

    def test_deduplication_preserves_first_seen_order(self) -> None:
        result = check_output(
            [
                {"url": REEL_URL, "author_username": "theanomalyvault"},
                {"url": SECOND_URL, "author_username": "revive.wav"},
                {"url": REEL_URL, "author_username": "theanomalyvault"},
            ]
        )

        self.assertEqual([reel.url for reel in result], [REEL_URL, SECOND_URL])

    def test_deduplication_prefers_known_author(self) -> None:
        for authors in [(None, "theanomalyvault"), ("theanomalyvault", None)]:
            with self.subTest(authors=authors):
                result = check_output(
                    [{"url": REEL_URL, "author_username": author} for author in authors]
                )

                self.assertEqual(
                    [reel.model_dump() for reel in result],
                    [{"url": REEL_URL, "author_username": "theanomalyvault"}],
                )

    def test_conflicting_authors_stay_unknown(self) -> None:
        for authors in [
            ("first", "second"),
            ("first", "second", "first"),
            ("first", "second", None),
            (None, "first", "second"),
        ]:
            with self.subTest(authors=authors):
                result = check_output(
                    [{"url": REEL_URL, "author_username": author} for author in authors]
                )

                self.assertEqual(
                    [reel.model_dump() for reel in result],
                    [{"url": REEL_URL, "author_username": None}],
                )

    def test_preserves_shortcode_case(self) -> None:
        result = check_output(
            [
                {"url": "https://www.instagram.com/reel/AbC/", "author_username": None},
                {"url": "https://www.instagram.com/reel/abc/", "author_username": None},
            ]
        )

        self.assertEqual(
            [reel.url for reel in result],
            [
                "https://www.instagram.com/reel/AbC/",
                "https://www.instagram.com/reel/abc/",
            ],
        )
