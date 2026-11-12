import socket
import threading
import time
import unittest

from aetherbond.core.adapter import NetworkAdapter
from aetherbond.core.proxy import MultiNicProxy


class TestProxyServer(unittest.TestCase):
    def test_proxy_lifecycle(self):
        adapter = NetworkAdapter(name="Loopback", if_index=1, ipv4="127.0.0.1", status="Up")
        proxy = MultiNicProxy(
            host="127.0.0.1",
            socks5_port=11080,
            http_port=18080,
            adapters=[adapter],
        )

        t = threading.Thread(target=proxy.start, args=(False,), daemon=True)
        t.start()
        time.sleep(0.3)

        # Check port listening
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        try:
            s.connect(("127.0.0.1", 11080))
            # Send SOCKS5 greeting
            s.sendall(b"\x05\x01\x00")
            resp = s.recv(2)
            self.assertEqual(resp, b"\x05\x00")
        finally:
            s.close()
            proxy.stop()


if __name__ == "__main__":
    unittest.main()
