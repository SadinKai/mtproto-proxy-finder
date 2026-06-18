"""
Unit tests for the MTProto core validation module.
Run using: python -m unittest tests/test_mtproto.py
"""

import unittest
import base64
import os
from core.mtproto import (
    parse_secret,
    MyRandom,
    MTProxyFakeTLSClientCodec,
    init_obfuscated_header
)


class TestMTProtoSecretParser(unittest.TestCase):
    def test_plain_hex_secret(self):
        secret_hex = "d3db4616238b725c15e2195ec47eb384"
        raw_secret, is_faketls, is_dd, domain = parse_secret(secret_hex)
        self.assertEqual(raw_secret, bytes.fromhex(secret_hex))
        self.assertFalse(is_faketls)
        self.assertFalse(is_dd)
        self.assertIsNone(domain)

    def test_dd_padded_hex_secret(self):
        secret_hex = "ddd3db4616238b725c15e2195ec47eb384"
        raw_secret, is_faketls, is_dd, domain = parse_secret(secret_hex)
        self.assertEqual(raw_secret, bytes.fromhex(secret_hex[2:]))
        self.assertFalse(is_faketls)
        self.assertTrue(is_dd)
        self.assertIsNone(domain)

    def test_ee_faketls_hex_secret(self):
        secret_hex = "eed3db4616238b725c15e2195ec47eb384676f6f676c652e636f6d"
        raw_secret, is_faketls, is_dd, domain = parse_secret(secret_hex)
        self.assertEqual(raw_secret, bytes.fromhex("d3db4616238b725c15e2195ec47eb384"))
        self.assertTrue(is_faketls)
        self.assertFalse(is_dd)
        self.assertEqual(domain, b"google.com")

    def test_base64_plain_secret(self):
        raw = os.urandom(16)
        b64 = base64.b64encode(raw).decode()
        raw_secret, is_faketls, is_dd, domain = parse_secret(b64)
        self.assertEqual(raw_secret, raw)
        self.assertFalse(is_faketls)
        self.assertFalse(is_dd)

    def test_base64_faketls_secret(self):
        raw = b"\xee" + os.urandom(16) + b"yahoo.com"
        b64 = base64.b64encode(raw).decode()
        raw_secret, is_faketls, is_dd, domain = parse_secret(b64)
        self.assertEqual(raw_secret, raw[1:17])
        self.assertTrue(is_faketls)
        self.assertEqual(domain, b"yahoo.com")


class TestMyRandom(unittest.TestCase):
    def test_random_bytes_len(self):
        r = MyRandom()
        b = r.getrandbytes(100)
        self.assertEqual(len(b), 100)
        b2 = r.getrandbytes(100)
        self.assertNotEqual(b, b2)

    def test_getrandbits(self):
        r = MyRandom()
        bits = r.getrandbits(16)
        self.assertTrue(0 <= bits < 65536)


class TestFakeTLSClientCodec(unittest.TestCase):
    def test_client_hello_generation(self):
        secret = os.urandom(16)
        domain = b"github.com"
        codec = MTProxyFakeTLSClientCodec(secret, domain)
        packet = codec.build_new_client_hello_packet()
        self.assertEqual(len(packet), 517)
        self.assertTrue(packet.startswith(b"\x16\x03\x01"))


class TestObfuscatedHeader(unittest.TestCase):
    def test_header_generation(self):
        secret = os.urandom(16)
        dc_id = 2
        tag = b"\xdd\xdd\xdd\xdd"
        header, encryptor, decryptor = init_obfuscated_header(secret, dc_id, tag)
        self.assertEqual(len(header), 64)
        self.assertNotEqual(header[0], 0xef)


if __name__ == "__main__":
    unittest.main()
