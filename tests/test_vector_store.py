import unittest
from tempfile import TemporaryDirectory
import chromadb
from app.services.vector_store import VectorStore


class VectorStoreTests(unittest.TestCase):
    def test_cosine_ranking_persistence_and_upsert(self):
        with TemporaryDirectory() as directory:
            store = VectorStore(persist_directory=directory)
            # Magnitudes deliberately differ: L2 would favor the perpendicular vector.
            store.upsert_chunks(['aligned', 'perpendicular'], [[10., 0.], [0., 1.]], 'sample.pdf')
            self.assertEqual(store.collection.configuration['hnsw']['space'], 'cosine')
            result = store.search([1., 0.], 2)
            self.assertEqual(result['documents'][0], ['aligned', 'perpendicular'])
            self.assertAlmostEqual(result['distances'][0][0], 0., places=6)
            self.assertAlmostEqual(result['distances'][0][1], 1., places=6)
            self.assertEqual(result['metadatas'][0][0], {'source': 'sample.pdf', 'chunk_index': 0})
            store.upsert_chunks(['updated'], [[10., 0.]], 'sample.pdf')
            reopened = VectorStore(persist_directory=directory)
            self.assertEqual(reopened.collection.count(), 2)
            self.assertEqual(reopened.search([1., 0.], 1)['documents'][0], ['updated'])

    def test_existing_l2_collection_is_rejected(self):
        with TemporaryDirectory() as directory:
            client = chromadb.PersistentClient(path=directory)
            client.create_collection('documents_cosine', configuration={'hnsw': {'space': 'l2'}})
            with self.assertRaisesRegex(ValueError, 'does not use cosine'):
                VectorStore(persist_directory=directory)
