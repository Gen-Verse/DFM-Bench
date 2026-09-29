import copy
import unittest
from dfm_bench.source_spans import FIELDS, split_source, selection_to_card


class SourceSpanTests(unittest.TestCase):
    def selection(self, spans):
        return {**dict.fromkeys(FIELDS), "claim": [spans[0]["id"]]}

    def test_unicode_code_and_newlines_roundtrip(self):
        source = "标题\r\n\n```python\n" + "α🙂x=" * 900 + "\n```\n  trailing  \n"
        spans = split_source(source)
        self.assertEqual("".join(s["text"] for s in spans), source)
        self.assertTrue(all(0 < len(s["text"]) <= 1200 for s in spans))
        self.assertEqual(spans, split_source(source))
        for span in spans:
            self.assertEqual(source[span["start"]:span["end"]], span["text"])

    def test_selection_preserves_exact_whitespace_and_two_quotes(self):
        source = " claim\r\n  test\n" * 150
        spans = split_source(source, 70)
        selected = self.selection(spans)
        selected["evidence"] = [spans[1]["id"], spans[2]["id"]]
        card = selection_to_card(source, spans, selected)
        self.assertEqual(card["claim"], [spans[0]["text"]])
        self.assertEqual(card["evidence"], [spans[1]["text"], spans[2]["text"]])
        self.assertIsNone(card["alternatives"])

    def test_long_unbroken_token_and_tiny_limit(self):
        for limit in (1, 3, 1200):
            spans = split_source("界" * 2501, limit)
            self.assertEqual("".join(s["text"] for s in spans), "界" * 2501)
            self.assertLessEqual(max(len(s["text"]) for s in spans), limit)

    def test_mutations_rejected_even_in_unselected_span(self):
        source = "hello scientific world " * 100
        spans = split_source(source)
        for field, value in (("text", "fake"), ("id", "fake"), ("start", True), ("end", 999999), ("source_sha256", "0"*64), ("span_sha256", "0"*64)):
            with self.subTest(field=field):
                bad = copy.deepcopy(spans); bad[-1][field] = value
                with self.assertRaises(ValueError):
                    selection_to_card(source, bad, self.selection(spans))
        with self.assertRaises(ValueError):
            selection_to_card(source + "!", spans, self.selection(spans))

    def test_invalid_selections_and_required_claim(self):
        source = "abc"; spans = split_source(source); good = self.selection(spans)
        bads = [dict(good, extra=None), {k:v for k,v in good.items() if k != "evidence"}]
        for value in (None, [], ["unknown"], [spans[0]["id"]]*2, [1], "span", [spans[0]["id"]]*3):
            bads.append(dict(good, claim=value))
        for bad in bads:
            with self.assertRaises(ValueError):
                selection_to_card(source, spans, bad)

    def test_incomplete_or_duplicate_bank(self):
        source = "a"*2500; spans = split_source(source)
        for bad in (spans[:-1], spans + [spans[0]], spans[1:]):
            with self.assertRaises(ValueError):
                selection_to_card(source, bad, self.selection(spans))

    def test_empty_source_and_invalid_limits(self):
        self.assertEqual(split_source(""), [])
        with self.assertRaises(ValueError):
            selection_to_card("", [], dict.fromkeys(FIELDS))
        for limit in (0, -1, 1201, True, 1.5):
            with self.assertRaises(ValueError):
                split_source("abc", limit)


if __name__ == "__main__":
    unittest.main()
