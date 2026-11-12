import unittest

from aetherbond.core.adapter import AdapterManager, NetworkAdapter, classify_adapter_type


class TestAdapterManager(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(classify_adapter_type("Wi-Fi", "Intel Wi-Fi 6"), "wifi")
        self.assertEqual(classify_adapter_type("Ethernet", "Realtek GbE Controller"), "ethernet")
        self.assertEqual(classify_adapter_type("veth1234", "Docker virtual interface"), "virtual")
        self.assertEqual(classify_adapter_type("Cellular", "LTE Modem"), "cellular")

    def test_speed_display(self):
        a1 = NetworkAdapter(name="Gigabit", link_speed=1_000_000_000)
        self.assertEqual(a1.speed_display, "1.0 Gbps")

        a2 = NetworkAdapter(name="Wifi", link_speed=433_000_000)
        self.assertEqual(a2.speed_display, "433 Mbps")

    def test_discovery_and_serialization(self):
        mgr = AdapterManager()
        adapters = mgr.get_adapters()
        self.assertIsInstance(adapters, list)
        if adapters:
            d = adapters[0].to_dict()
            self.assertIn("name", d)
            self.assertIn("if_index", d)
            self.assertIn("status", d)


if __name__ == "__main__":
    unittest.main()
