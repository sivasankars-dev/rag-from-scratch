import unittest
from services.better_chunker import BetterChunker


class BetterChunkTest(unittest.TestCase):
    def test_split_sentences(self):
        chunker = BetterChunker()

        text = (
            "Employees get 20 days of annual leave. "
            "Leave requests must be submitted through HR. "
            "Managers approve the requests."
        )

        sentences = chunker.split_sentences(text)

        self.assertEqual(
            sentences,
            [
                "Employees get 20 days of annual leave.",
                "Leave requests must be submitted through HR.",
                "Managers approve the requests.",
            ],
        )

    def test_build_chunks(self):
        chunker = BetterChunker()

        sentences = [
            "First sentence.",
            "Second sentence.",
            "Third sentence.",
        ]

        chunks = chunker.build_chunks(sentences, 35)

        self.assertEqual(
            chunks,
            [
                "First sentence. Second sentence.",
                "Third sentence.",
            ],
        )

    def test_build_chunks_without_overlap(self):
        chunker = BetterChunker()

        sentences = [
            "First sentence.",
            "Second sentence.",
            "Third sentence.",
            "Fourth sentence.",
        ]

        chunks = chunker.build_chunks(
            sentences,
            max_chunk_size=35,
            overlap_sentences=0,
        )

        self.assertEqual(
            chunks,
            [
                "First sentence. Second sentence.",
                "Third sentence. Fourth sentence.",
            ],
        )

    def test_build_chunks_with_overlap(self):
        chunker = BetterChunker()

        sentences = [
            "First sentence.",
            "Second sentence.",
            "Third sentence.",
            "Fourth sentence.",
        ]

        chunks = chunker.build_chunks(
            sentences,
            max_chunk_size=35,
            overlap_sentences=1,
        )

        self.assertEqual(
            chunks,
            [
                "First sentence. Second sentence.",
                "Second sentence. Third sentence.",
                "Third sentence. Fourth sentence.",
            ],
        )

    def test_invalid_max_chunk_size(self):
        chunker = BetterChunker()

        with self.assertRaises(ValueError):
            chunker.build_chunks(["Hello."], max_chunk_size=0)

    def test_negative_overlap(self):
        chunker = BetterChunker()

        with self.assertRaises(ValueError):
            chunker.build_chunks(
                ["Hello."],
                max_chunk_size=100,
                overlap_sentences=-1,
            )

    def test_build_chunks_with_oversized_sentence(self):
        chunker = BetterChunker()

        sentences = [
            "ABC.",
            "123456789012345",
            "XYZ.",
        ]

        chunks = chunker.build_chunks(
            sentences,
            max_chunk_size=10,
            overlap_sentences=0,
        )

        self.assertEqual(
            chunks,
            [
                "ABC.",
                "1234567890",
                "12345",
                "XYZ.",
            ],
        )

    def test_oversized_sentence_with_overlap(self):
        chunker = BetterChunker()

        sentences = [
            "First.",
            "123456789012345",
            "Last.",
        ]

        chunks = chunker.build_chunks(
            sentences,
            max_chunk_size=10,
            overlap_sentences=1,
        )

        self.assertEqual(
            chunks,
            [
                "First.",
                "1234567890",
                "12345",
                "Last.",
            ],
        )

    def test_overlap_should_not_exceed_max_chunk_size(self):
        chunker = BetterChunker()

        sentences = [
            "12345678.",
            "abcdefg.",
        ]

        chunks = chunker.build_chunks(
            sentences,
            max_chunk_size=10,
            overlap_sentences=1,
        )

        self.assertEqual(
            chunks,
            [
                "12345678.",
                "abcdefg.",
            ],
        )

    def test_oversized_sentence_preserves_space_before_it(self):
        chunker = BetterChunker()

        sentences = [
            "AAA.",
            "BBB.",
            "12345678901",
        ]

        chunks = chunker.build_chunks(
            sentences,
            max_chunk_size=10,
            overlap_sentences=0,
        )

        self.assertEqual(
            chunks,
            [
                "AAA. BBB.",
                "1234567890",
                "1",
            ],
        )

    def test_oversized_sentence_with_large_overlap(self):
        chunker = BetterChunker()

        sentences = [
            "A.",
            "12345678901",
        ]

        chunks = chunker.build_chunks(
            sentences,
            max_chunk_size=10,
            overlap_sentences=2,
        )

        self.assertEqual(
            chunks,
            [
                "A.",
                "1234567890",
                "1",
            ],
        )
