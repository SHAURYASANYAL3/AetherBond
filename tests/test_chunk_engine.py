import os
import tempfile
import unittest

from aetherbond.core.chunk_engine import (
    CHUNK_STATUS_COMPLETED,
    CHUNK_STATUS_DOWNLOADING,
    CHUNK_STATUS_PENDING,
    Chunk,
    ChunkEngine,
)


class TestChunkEngine(unittest.TestCase):
    def test_partitioning(self):
        # 10 MB total size, 2 MB chunk size = 5 chunks
        total = 10 * 1024 * 1024
        chunk_sz = 2 * 1024 * 1024
        engine = ChunkEngine(total_size=total, chunk_size=chunk_sz)

        self.assertEqual(len(engine.chunks), 5)
        self.assertEqual(engine.chunks[0].start, 0)
        self.assertEqual(engine.chunks[0].end, chunk_sz - 1)
        self.assertEqual(engine.chunks[4].end, total - 1)

    def test_dynamic_allocation(self):
        engine = ChunkEngine(total_size=1000, chunk_size=200)
        self.assertEqual(len(engine.chunks), 5)

        c1 = engine.get_next_chunk("Wi-Fi")
        self.assertIsNotNone(c1)
        self.assertEqual(c1.id, 0)
        self.assertEqual(c1.assigned_adapter, "Wi-Fi")
        self.assertEqual(c1.status, CHUNK_STATUS_DOWNLOADING)

        c2 = engine.get_next_chunk("Ethernet")
        self.assertIsNotNone(c2)
        self.assertEqual(c2.id, 1)
        self.assertEqual(c2.assigned_adapter, "Ethernet")

    def test_progress_and_completion(self):
        engine = ChunkEngine(total_size=500, chunk_size=250)
        c0 = engine.get_next_chunk("Wi-Fi")
        engine.update_progress(c0.id, 250)
        engine.mark_completed(c0.id)

        stats = engine.get_progress_stats()
        self.assertEqual(stats["completed_chunks"], 1)
        self.assertEqual(stats["percent"], 50.0)
        self.assertFalse(engine.is_all_completed())

        c1 = engine.get_next_chunk("Ethernet")
        engine.update_progress(c1.id, 250)
        engine.mark_completed(c1.id)
        self.assertTrue(engine.is_all_completed())

    def test_save_and_load_state(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            engine = ChunkEngine(total_size=1000, chunk_size=250)
            c = engine.get_next_chunk("Wi-Fi")
            engine.mark_completed(c.id)
            engine.save_state(tmp_path)

            restored = ChunkEngine.load_state(tmp_path)
            self.assertIsNotNone(restored)
            self.assertEqual(restored.total_size, 1000)
            self.assertEqual(restored.chunks[0].status, CHUNK_STATUS_COMPLETED)
            self.assertEqual(restored.chunks[1].status, CHUNK_STATUS_PENDING)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()
