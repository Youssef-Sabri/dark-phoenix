import unittest

from clip_validation import parse_clip_moments


class ParseClipMomentsTests(unittest.TestCase):
    def setUp(self):
        self.transcript = [{"start": 0.0, "end": 180.0, "word": "test"}]

    def test_accepts_fenced_json_and_sorts_non_overlapping_clips(self):
        response = """```json
[
  {"start": 90, "end": 130},
  {"start": 0, "end": 45},
  {"start": 40, "end": 80}
]
```"""

        self.assertEqual(
            parse_clip_moments(response, self.transcript),
            [
                {"start": 0.0, "end": 45.0},
                {"start": 90.0, "end": 130.0},
            ],
        )

    def test_rejects_unsafe_or_out_of_range_timestamps(self):
        response = """[
          {"start": "0; rm -rf /", "end": 45},
          {"start": -1, "end": 40},
          {"start": 0, "end": 10},
          {"start": 0, "end": 61},
          {"start": 150, "end": 190}
        ]"""

        result = parse_clip_moments(response, self.transcript)
        # None of the unsafe/out-of-range inputs may survive. The 3-clip
        # guarantee fallback may synthesize safe non-overlapping highlights
        # instead (this transcript is 180 s), so assert the safety invariants
        # that must hold for every returned moment.
        for moment in result:
            self.assertTrue(all(isinstance(value, float) for value in moment.values()))
            self.assertGreaterEqual(moment["start"], 0.0)
            self.assertGreaterEqual(moment["end"] - moment["start"], 30.0)
            self.assertLessEqual(moment["end"] - moment["start"], 60.0)
            self.assertLessEqual(moment["end"], self.transcript[0]["end"] + 1.0)
        self.assertGreaterEqual(len(result), 3)

    def test_requires_a_json_list(self):
        with self.assertRaisesRegex(ValueError, "JSON list"):
            parse_clip_moments('{"start": 0, "end": 45}', self.transcript)


if __name__ == "__main__":
    unittest.main()
