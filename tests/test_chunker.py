import unittest
from app.services.chunker import chunk_text


class ChunkTests(unittest.TestCase):
    def test_windows_overlap_and_last_fragment(self):
        self.assertEqual(chunk_text('abcdefghijkl', 5, 2),
                         ['abcde', 'defgh', 'ghijk', 'jkl'])

    def test_empty_and_whitespace(self):
        self.assertEqual(chunk_text('', 5, 2), [])
        self.assertEqual(chunk_text('     ', 5, 2), [])
        self.assertEqual(chunk_text(' hi ', 5, 2), ['hi'])

    def test_invalid_configuration(self):
        for size, overlap in [(0, 0), (-1, 0), (5, -1), (5, 5), (5, 6)]:
            with self.subTest(size=size, overlap=overlap), self.assertRaises(ValueError):
                chunk_text('abc', size, overlap)
        with self.assertRaisesRegex(ValueError, 'greater than 0'):
            chunk_text('abc', 0, 0)
