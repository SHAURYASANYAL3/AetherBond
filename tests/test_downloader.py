import hashlib
import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from aetherbond.core.adapter import NetworkAdapter
from aetherbond.core.downloader import TurboDownloader

TEST_PAYLOAD = os.urandom(2 * 1024 * 1024)  # 2MB random data
EXPECTED_SHA = hashlib.sha256(TEST_PAYLOAD).hexdigest()


class MockRangeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(TEST_PAYLOAD)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            parts = range_header.replace("bytes=", "").split("-")
            start = int(parts[0])
            end = int(parts[1]) if parts[1] else len(TEST_PAYLOAD) - 1
            end = min(end, len(TEST_PAYLOAD) - 1)

            chunk = TEST_PAYLOAD[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(TEST_PAYLOAD)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(TEST_PAYLOAD)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(TEST_PAYLOAD)


class TestTurboDownloader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 18888), MockRangeHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_parallel_chunk_download(self):
        temp_dir = tempfile.mkdtemp()
        try:
            adapter = NetworkAdapter(
                name="Loopback",
                if_index=1,
                ipv4="127.0.0.1",
                status="Up",
                is_internet_ready=True,
            )

            dl = TurboDownloader(
                url="http://127.0.0.1:18888/testfile.bin",
                output_dir=temp_dir,
                adapters=[adapter],
                streams_per_adapter=4,
            )

            success = dl.start(blocking=True)
            self.assertTrue(success)
            self.assertTrue(os.path.exists(dl.target_path))
            self.assertEqual(os.path.getsize(dl.target_path), len(TEST_PAYLOAD))

            with open(dl.target_path, "rb") as f:
                data = f.read()
            self.assertEqual(hashlib.sha256(data).hexdigest(), EXPECTED_SHA)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
