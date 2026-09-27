"""Small integration check using the real PDF, model and an isolated Chroma store."""
import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.chunker import chunk_text
from app.services.document_loader import extract_text_from_pdf
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore
from scripts.run_similarity_demo import cosine_similarity

class RetrievalTests(unittest.TestCase):
    def test_pdf_to_ranked_chunks(self):
        sample = Path(__file__).resolve().parents[1] / 'data/documents/company_policy.pdf'
        text = extract_text_from_pdf(sample)
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
        self.assertEqual(len(text), 343)
        self.assertEqual(len(chunks), 5)
        service = EmbeddingService()
        vectors = service.embed_texts(chunks)
        query = service.embed_text('How many annual leave days do I get?')
        self.assertEqual(len(query), 384)
        self.assertEqual(len(vectors), 5)
        for vector in [query, *vectors]:
            self.assertEqual(len(vector), 384)
            self.assertTrue(all(math.isfinite(x) for x in vector))
        with TemporaryDirectory() as directory:
            store = VectorStore(persist_directory=directory)
            for _ in range(2):
                store.upsert_chunks(chunks, vectors, sample.name)
            self.assertEqual(store.collection.count(), 5)
            result = store.search(query, top_k=2)
            self.assertEqual(len(result['documents'][0]), 2)
            self.assertEqual(result['distances'][0], sorted(result['distances'][0]))
            self.assertIn('20 days of annual leave', result['documents'][0][0])
            for doc, metadata, distance in zip(result['documents'][0],
                                               result['metadatas'][0], result['distances'][0]):
                index = metadata['chunk_index']
                self.assertEqual(metadata['source'], sample.name)
                self.assertEqual(doc, chunks[index])
                self.assertAlmostEqual(1 - distance,
                                       cosine_similarity(query, vectors[index]), places=5)
