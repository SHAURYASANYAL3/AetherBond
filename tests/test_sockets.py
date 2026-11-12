import socket
import sys
import unittest

from aetherbond.core.adapter import NetworkAdapter
from aetherbond.core.socket_factory import BoundSocketFactory


class TestSocketFactory(unittest.TestCase):
    def test_create_and_bind_socket(self):
        # Create dummy adapter with index 1
        adapter = NetworkAdapter(
            name="TestAdapter",
            if_index=1,
            ipv4="127.0.0.1",
            status="Up",
        )

        sock = BoundSocketFactory.create_socket(adapter, timeout=2.0)
        self.assertIsInstance(sock, socket.socket)
        sock.close()


if __name__ == "__main__":
    unittest.main()
