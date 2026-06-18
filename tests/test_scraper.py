"""
Unit tests for the Scraper and Normalizer modules.
Run using: python -m unittest tests/test_scraper.py
"""

import unittest
from scrapers.collector import normalize_proxy_url


class TestProxyURLNormalizer(unittest.TestCase):
    def test_valid_https_url(self):
        url = "https://t.me/proxy?server=127.0.0.1&port=443&secret=eed3db4616238b725c15e2195ec47eb384676f6f676c652e636f6d"
        normalized = normalize_proxy_url(url)
        self.assertIsNotNone(normalized)
        self.assertTrue(normalized.startswith("https://t.me/proxy?"))
        self.assertIn("server=127.0.0.1", normalized)
        self.assertIn("port=443", normalized)
        self.assertIn("secret=eed3db4616238b725c15e2195ec47eb384676f6f676c652e636f6d", normalized)

    def test_valid_tg_url(self):
        url = "tg://proxy?server=myproxy.com&port=8888&secret=d3db4616238b725c15e2195ec47eb384"
        normalized = normalize_proxy_url(url)
        self.assertIsNotNone(normalized)
        self.assertTrue(normalized.startswith("https://t.me/proxy?"))
        self.assertIn("server=myproxy.com", normalized)
        self.assertIn("port=8888", normalized)
        self.assertIn("secret=d3db4616238b725c15e2195ec47eb384", normalized)

    def test_html_encoded_ampersands(self):
        url = "https://t.me/proxy?server=127.0.0.1&amp;port=443&amp;secret=d3db4616238b725c15e2195ec47eb384"
        normalized = normalize_proxy_url(url)
        self.assertIsNotNone(normalized)
        self.assertIn("port=443", normalized)
        self.assertIn("secret=d3db4616238b725c15e2195ec47eb384", normalized)

    def test_missing_params(self):
        url = "https://t.me/proxy?server=127.0.0.1&port=443"
        self.assertIsNone(normalize_proxy_url(url))

    def test_invalid_port(self):
        url_high = "https://t.me/proxy?server=127.0.0.1&port=70000&secret=d3db4616238b725c15e2195ec47eb384"
        url_neg = "https://t.me/proxy?server=127.0.0.1&port=-10&secret=d3db4616238b725c15e2195ec47eb384"
        self.assertIsNone(normalize_proxy_url(url_high))
        self.assertIsNone(normalize_proxy_url(url_neg))


if __name__ == "__main__":
    unittest.main()
