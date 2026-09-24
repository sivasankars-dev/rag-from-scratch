import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from app.main import app
from app.services.document_loader import extract_text_from_pdf

SAMPLE = Path(__file__).resolve().parents[1] / 'data/documents/company_policy.pdf'


class DocumentTests(unittest.TestCase):
    def test_sample_and_page_separator(self):
        text = extract_text_from_pdf(SAMPLE)
        self.assertEqual(len(text), 343)
        self.assertIn('20 days of annual leave', text)
        page = PdfReader(SAMPLE).pages[0]
        writer = PdfWriter()
        writer.add_page(page)
        writer.add_page(page)
        stream = BytesIO()
        writer.write(stream)
        stream.seek(0)
        self.assertEqual(extract_text_from_pdf(stream), text + '\n' + text)

    def test_upload_stays_inside_upload_directory(self):
        with TemporaryDirectory() as directory:
            upload_dir = Path(directory) / 'uploads'
            # Replace only the route's relative upload directory; keep filename parsing real.
            real_path = Path
            def route_path(value):
                return upload_dir if value == 'docs/uploads' else real_path(value)
            with patch('app.main.Path', side_effect=route_path):
                client = TestClient(app)
                self.assertEqual(client.get('/health').json(), {'status': 'ok'})
                response = client.post('/documents/upload', files={
                    'file': ('../outside.pdf', SAMPLE.read_bytes(), 'application/pdf')
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['text_length'], 343)
                self.assertEqual(response.json()['chunk_count'], 4)
                self.assertTrue((upload_dir / 'outside.pdf').exists())
                self.assertFalse((Path(directory) / 'outside.pdf').exists())
                self.assertEqual(client.post('/documents/upload', files={
                    'file': ('sample.txt', b'hello', 'text/plain')
                }).status_code, 400)
