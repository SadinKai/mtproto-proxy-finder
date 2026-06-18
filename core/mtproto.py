"""
MTProto and FakeTLS protocol implementation in Python 3.13.
Implements Obfuscated2, FakeTLS handshake, packet framing, and req_pq_multi checking
with phase-by-phase latency benchmarking.
"""

import os
import time
import struct
import random
import socket
import hashlib
import hmac
import base64
import asyncio
from typing import Tuple, Optional, Callable, Dict

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend


class CryptographyEncryptorAdapter:
    def __init__(self, key: bytes, iv_int: int):
        iv_bytes = int.to_bytes(iv_int, 16, "big")
        cipher = Cipher(algorithms.AES(key), modes.CTR(iv_bytes), backend=default_backend())
        self.encryptor = cipher.encryptor()

    def encrypt(self, data: bytes) -> bytes:
        return self.encryptor.update(data)


class MyRandom(random.Random):
    """
    AES-CTR based random stream generator designed to produce high-entropy
    random bytes to avoid simple firewall pattern matching on the ClientHello.
    """
    def __init__(self):
        super().__init__()
        key = bytes([random.randrange(256) for _ in range(32)])
        iv = random.randrange(256 ** 16)
        self.encryptor = CryptographyEncryptorAdapter(key, iv)
        self.buffer = bytearray()

    def getrandbits(self, k: int) -> int:
        numbytes = (k + 7) // 8
        return int.from_bytes(self.getrandbytes(numbytes), 'big') >> (numbytes * 8 - k)

    def getrandbytes(self, n: int) -> bytes:
        chunk_size = 512
        while n > len(self.buffer):
            raw_bits = super().getrandbits(chunk_size * 8)
            data = int.to_bytes(raw_bits, chunk_size, "big")
            self.buffer += self.encryptor.encrypt(data)

        result = self.buffer[:n]
        self.buffer = self.buffer[n:]
        return bytes(result)


# Global high-entropy random source
myrandom = MyRandom()


def gen_x25519_public_key() -> bytes:
    """
    Generates a mock x25519 public key that matches the key exchange format
    by generating a value that has a modular square root.
    """
    P = 2 ** 255 - 19
    n = myrandom.randrange(P)
    return int.to_bytes((n * n) % P, length=32, byteorder="little")


def parse_secret(secret_str: str) -> Tuple[bytes, bool, bool, Optional[bytes]]:
    """
    Decodes the MTProxy secret string (supporting hex, base64) and parses its metadata.
    Returns a tuple: (raw_secret_16_bytes, is_faketls, is_dd_padded, domain_bytes_or_none)
    """
    is_hex = True
    try:
        secret_bytes = bytes.fromhex(secret_str)
    except ValueError:
        is_hex = False

    if not is_hex:
        # Pad base64 string if necessary
        padded = secret_str + "=" * (-len(secret_str) % 4)
        try:
            secret_bytes = base64.urlsafe_b64decode(padded)
        except Exception:
            try:
                secret_bytes = base64.b64decode(padded)
            except Exception as e:
                raise ValueError(f"Secret is neither valid hex nor valid base64: {e}")

    is_faketls = False
    is_dd = False
    domain = None
    raw_secret = b""

    # Analyze prefix and size
    if len(secret_bytes) > 17 and secret_bytes[0] == 0xee:
        is_faketls = True
        raw_secret = secret_bytes[1:17]
        domain = secret_bytes[17:]
    elif len(secret_bytes) == 17 and secret_bytes[0] == 0xdd:
        is_dd = True
        raw_secret = secret_bytes[1:]
    elif len(secret_bytes) == 16:
        raw_secret = secret_bytes
    else:
        # Fallback for base64 links that do not have 0xee explicitly prepended but are long
        if len(secret_bytes) > 16:
            is_faketls = True
            raw_secret = secret_bytes[:16]
            domain = secret_bytes[16:]
        else:
            raise ValueError(f"Invalid secret length ({len(secret_bytes)} bytes)")

    return raw_secret, is_faketls, is_dd, domain


class MTProxyFakeTLSClientCodec:
    """
    Builds the TLS ClientHello packet with correct SNI and verification HMAC,
    and validates the ServerHello returned by the MTProxy.
    """
    def __init__(self, secret: bytes, domain: bytes):
        self.secret = secret
        self.domain = domain
        self.client_hello_dict = {
            'content_type': b'\x16',  # handshake (22)
            'version': b'\x03\x01',  # TLS 1.0
            'len': b'\x02\x00',  # 512 bytes placeholder
            'handshake_type': b'\x01',  # ClientHello
            'handshake_len': b'\x00\x01\xfc',  # Handshake length
            'handshake_version': b'\x03\x03',  # TLS 1.2
            'random': b'\x00' * 32,
            'session_id_len': b'\x20',
            'session_id': b'\x00' * 32,
            'cipher_suites_len': b'\x00\x20',
            'cipher_suites': b"\xfa\xfa\x13\x01\x13\x02\x13\x03\xc0\x2b\xc0\x2f\xc0\x2c\xc0\x30"
                             b"\xcc\xa9\xcc\xa8\xc0\x13\xc0\x14\x00\x9c\x00\x9d\x00\x2f\x00\x35",
            'compression_methods_len': b'\x01',
            'compression_methods': b'\x00',
            'extensions_len': b'\x01\x93',
            'ext_reserved_1': b"\x4a\x4a\x00\x00",
            'ext_server_name_type': b'\x00\x00',
            'ext_server_name_len': b'\x00\x00',
            'ext_server_name_indication_list_len': b'\x00\x00',
            'ext_server_name_indication_type': b'\x00',
            'ext_server_name_indication_len': b'\x00\x00',
            'ext_server_name_indication': b'\x00',
            'ext_extended_master_secret': b"\x00\x17\x00\x00",
            'ext_renegotiation_info': b"\xff\x01\x00\x01\x00",
            'ext_supported_groups': b"\x00\x0a\x00\x0a\x00\x08\xba\xba\x00\x1d\x00\x17\x00\x18",
            'ext_ec_point_formats': b"\x00\x0b\x00\x02\x01\x00",
            'ext_session_ticket': b"\x00\x23\x00\x00",
            'ext_alpn': b"\x00\x10\x00\x0e\x00\x0c\x02\x68\x32\x08\x68\x74\x74\x70\x2f\x31\x2e\x31",
            'ext_status_request': b"\x00\x05\x00\x05\x01\x00\x00\x00\x00",
            'ext_signature_algorithms': b"\x00\x0d\x00\x12\x00\x10\x04\x03\x08\x04\x04"
                                        b"\x01\x05\x03\x08\x05\x05\x01\x08\x06\x06\x01",
            'ext_signature_cert_timestamp': b"\x00\x12\x00\x00",
            'ext_key_share_type': b'\x00\x33',
            'ext_key_share_len': b'\x00\x2b',
            'ext_key_share_client_key_len': b'\x00\x29',
            'ext_key_share_reserved': b"\xba\xba\x00\x01\x00",
            'ext_key_share_group': b"\x00\x1d",
            'ext_key_share_exchange_len': b"\x00\x20",
            'ext_key_share_exchange': b"\x00",
            'ext_psk_key_exchange_modes': b"\x00\x2d\x00\x02\x01\x01",
            'ext_supported_tls_versions': b"\x00\x2b\x00\x0b\x0a\x9a\x9a\x03\x04\x03\x03\x03\x02\x03\x01",
            'ext_compress_cert': b"\x00\x1b\x00\x03\x02\x00\x02",
            'ext_reserved_2': b"\x1a\x1a\x00\x01\x00",
            'ext_padding_type': b'\x00\x15',
            'ext_padding_len': b'\x00\x00',
            'ext_padding': b'',
        }

    def build_new_client_hello_packet(self) -> bytes:
        self.client_hello_dict['session_id'] = myrandom.getrandbytes(32)

        # Set domain SNI details
        domain_len = len(self.domain)
        self.client_hello_dict['ext_server_name_len'] = int.to_bytes(2 + 1 + 2 + domain_len, 2, 'big')
        self.client_hello_dict['ext_server_name_indication_list_len'] = int.to_bytes(1 + 2 + domain_len, 2, 'big')
        self.client_hello_dict['ext_server_name_indication_len'] = int.to_bytes(domain_len, 2, 'big')
        self.client_hello_dict['ext_server_name_indication'] = self.domain

        # Set key share exchange
        self.client_hello_dict['ext_key_share_exchange'] = gen_x25519_public_key()

        # Fix TLS Record padding to match exactly 517 bytes
        self.client_hello_dict['ext_padding'] = b''
        current_len = sum(len(v) for v in self.client_hello_dict.values())
        padding_len = 517 - current_len
        self.client_hello_dict['ext_padding_len'] = int.to_bytes(padding_len, 2, 'big')
        self.client_hello_dict['ext_padding'] = b'\x00' * padding_len

        # Generate HMAC random field
        self.client_hello_dict['random'] = b'\x00' * 32
        glue = b''.join(self.client_hello_dict.values())
        digest = hmac.new(self.secret, glue, hashlib.sha256).digest()

        # XOR the last 4 bytes of random with local timestamp
        current_time = int(time.time()).to_bytes(4, 'little')
        xored_time = bytes(current_time[i] ^ digest[28 + i] for i in range(4))

        final_random = digest[:28] + xored_time
        self.client_hello_dict['random'] = final_random

        return b''.join(self.client_hello_dict.values())

    def verify_server_hello(self, server_hello: bytes) -> bool:
        try:
            if len(server_hello) < 127 + 6:
                return False
            if not server_hello.startswith(b'\x16\x03\x03'):
                return False
            if server_hello[127:127 + 9] != b'\x14\x03\x03\x00\x01\x01\x17\x03\x03':
                return False
            if server_hello[11 + 32 + 1:11 + 32 + 1 + 32] != self.client_hello_dict['session_id']:
                return False

            server_digest = server_hello[11:11 + 32]
            client_digest = self.client_hello_dict['random']

            server_hello_zeroed = server_hello[:11] + (b'\x00' * 32) + server_hello[11 + 32:]
            computed_digest = hmac.new(self.secret, client_digest + server_hello_zeroed, hashlib.sha256).digest()
            return server_digest == computed_digest
        except Exception:
            return False


class FakeTLSStreamReader:
    def __init__(self, reader: asyncio.StreamReader):
        self.reader = reader
        self.buf = bytearray()

    async def read_server_hello(self) -> bytes:
        server_hello = await self.reader.readexactly(127 + 6 + 3 + 2)
        http_data_len = int.from_bytes(server_hello[-2:], 'big')
        return server_hello + await self.reader.readexactly(http_data_len)

    async def read(self, n: int, ignore_buf: bool = False) -> bytes:
        if self.buf and not ignore_buf:
            data = self.buf
            self.buf = bytearray()
            return bytes(data)

        while True:
            tls_rec_type = await self.reader.readexactly(1)
            if not tls_rec_type:
                return b""

            if tls_rec_type not in (b"\x14", b"\x17"):
                raise ConnectionError(f"Bad TLS record type {tls_rec_type.hex()}")

            version = await self.reader.readexactly(2)
            if version != b"\x03\x03":
                raise ConnectionError(f"Unknown TLS version {version.hex()}")

            data_len = int.from_bytes(await self.reader.readexactly(2), "big")
            data = await self.reader.readexactly(data_len)

            if tls_rec_type == b"\x14":
                continue
            return data

    async def readexactly(self, n: int) -> bytes:
        while len(self.buf) < n:
            tls_data = await self.read(1, ignore_buf=True)
            if not tls_data:
                raise asyncio.IncompleteReadError(bytes(self.buf), n)
            self.buf += tls_data
        data, self.buf = self.buf[:n], self.buf[n:]
        return bytes(data)


class FakeTLSStreamWriter:
    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer

    def write(self, data: bytes):
        max_chunk_size = 16384
        for start in range(0, len(data), max_chunk_size):
            end = min(start + max_chunk_size, len(data))
            chunk = data[start:end]
            self.writer.write(b"\x17\x03\x03" + int.to_bytes(len(chunk), 2, "big"))
            self.writer.write(chunk)

    async def drain(self):
        await self.writer.drain()

    def close(self):
        self.writer.close()


def init_obfuscated_header(secret: bytes, dc_id: int, obfuscate_tag: bytes) -> Tuple[bytes, Cipher, Cipher]:
    if len(secret) != 16:
        raise ValueError("Secret must be exactly 16 bytes for key derivation")

    keywords = (b'PVrG', b'GET ', b'POST', b'\xee\xee\xee\xee')
    while True:
        rand_bytes = os.urandom(64)
        if (rand_bytes[0] != 0xef and
                rand_bytes[:4] not in keywords and
                rand_bytes[4:8] != b'\0\0\0\0'):
            break

    rand_arr = bytearray(rand_bytes)
    rand_reversed = rand_arr[55:7:-1]

    encrypt_key = hashlib.sha256(bytes(rand_arr[8:40]) + secret).digest()
    encrypt_iv = bytes(rand_arr[40:56])
    decrypt_key = hashlib.sha256(bytes(rand_reversed[:32]) + secret).digest()
    decrypt_iv = bytes(rand_reversed[32:48])

    encrypt_cipher = Cipher(algorithms.AES(encrypt_key), modes.CTR(encrypt_iv), backend=default_backend())
    decrypt_cipher = Cipher(algorithms.AES(decrypt_key), modes.CTR(decrypt_iv), backend=default_backend())

    encryptor = encrypt_cipher.encryptor()
    decryptor = decrypt_cipher.decryptor()

    rand_arr[56:60] = obfuscate_tag
    dc_bytes = dc_id.to_bytes(2, "little", signed=True)
    rand_arr[60:62] = dc_bytes

    encrypted_full = encryptor.update(bytes(rand_arr))
    rand_arr[56:64] = encrypted_full[56:64]

    return bytes(rand_arr), encryptor, decryptor


async def run_check(
    host: str,
    port: int,
    raw_secret: bytes,
    is_faketls: bool,
    domain: Optional[bytes],
    transport_mode: str,
    timeout: float,
    dc_id: int,
    debug_log: Optional[Callable[[str], None]]
) -> Tuple[str, Optional[Dict[str, float]]]:
    """
    Performs the check and returns (status, timing_dict)
    timing_dict contains: {resolve_ms, connect_ms, handshake_ms, total_ms}
    """
    resolve_ms = 0.0
    connect_ms = 0.0
    handshake_ms = 0.0
    total_start = time.perf_counter()

    # 1. DNS Resolution
    try:
        if debug_log:
            debug_log(f"Resolving host: {host}")
        resolve_start = time.perf_counter()
        loop = asyncio.get_running_loop()
        addr_info = await asyncio.wait_for(
            loop.getaddrinfo(host, port, proto=socket.IPPROTO_TCP),
            timeout=timeout
        )
        resolve_ms = (time.perf_counter() - resolve_start) * 1000.0
        ip = addr_info[0][4][0]
        if debug_log:
            debug_log(f"Resolved IP: {ip} in {resolve_ms:.1f}ms")
    except socket.gaierror as e:
        if debug_log:
            debug_log(f"DNS resolution failed: {e}")
        return "DNS_ERROR", None
    except asyncio.TimeoutError:
        return "TIMEOUT", None
    except Exception as e:
        if debug_log:
            debug_log(f"DNS error: {e}")
        return "DNS_ERROR", None

    # 2. TCP socket connection
    try:
        if debug_log:
            debug_log(f"Establishing TCP connection to {ip}:{port}...")
        connect_start = time.perf_counter()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout
        )
        connect_ms = (time.perf_counter() - connect_start) * 1000.0
        if debug_log:
            debug_log(f"TCP Connection established in {connect_ms:.1f}ms")
    except asyncio.TimeoutError:
        if debug_log:
            debug_log("TCP Connection timeout.")
        return "TIMEOUT", None
    except ConnectionRefusedError:
        if debug_log:
            debug_log("TCP Connection refused by remote host.")
        return "CONNECTION_REFUSED", None
    except Exception as e:
        if debug_log:
            debug_log(f"TCP connection failed: {e}")
        return "CONNECTION_REFUSED", None

    # 3. Protocol Handshake and validation exchange
    try:
        handshake_start = time.perf_counter()

        if is_faketls:
            if debug_log:
                debug_log(f"Performing FakeTLS handshake with domain: {domain.decode('utf-8', errors='ignore')}")
            faketls_codec = MTProxyFakeTLSClientCodec(raw_secret, domain)
            client_hello = faketls_codec.build_new_client_hello_packet()

            writer.write(client_hello)
            await writer.drain()

            tls_reader = FakeTLSStreamReader(reader)
            tls_writer = FakeTLSStreamWriter(writer)

            server_hello = await asyncio.wait_for(
                tls_reader.read_server_hello(),
                timeout=timeout
            )

            if not faketls_codec.verify_server_hello(server_hello):
                if debug_log:
                    debug_log("FakeTLS ServerHello verification failed.")
                writer.close()
                await writer.wait_closed()
                return "INVALID_SECRET", None

            active_reader = tls_reader
            active_writer = tls_writer
        else:
            active_reader = reader
            active_writer = writer

        if transport_mode == "abridged":
            obfuscate_tag = b'\xef\xef\xef\xef'
        elif transport_mode == "intermediate":
            obfuscate_tag = b'\xee\xee\xee\xee'
        else:
            obfuscate_tag = b'\xdd\xdd\xdd\xdd'

        header, encryptor, decryptor = init_obfuscated_header(raw_secret, dc_id, obfuscate_tag)

        active_writer.write(header)
        await active_writer.drain()

        nonce = os.urandom(16)
        msg_id = (int(time.time()) << 32) | 1

        message_data = b'\xf1\x8e\x7e\xbe' + nonce
        unencrypted_msg = b'\x00' * 8 + msg_id.to_bytes(8, 'little') + len(message_data).to_bytes(4, 'little') + message_data

        if transport_mode == "abridged":
            length = len(unencrypted_msg) >> 2
            if length < 127:
                len_prefix = struct.pack('B', length)
            else:
                len_prefix = b'\x7f' + int.to_bytes(length, 3, 'little')
            packet = len_prefix + unencrypted_msg
        elif transport_mode == "intermediate":
            packet = struct.pack('<I', len(unencrypted_msg)) + unencrypted_msg
        else:
            pad_size = random.randint(0, 3)
            padding = os.urandom(pad_size)
            packet = struct.pack('<I', len(unencrypted_msg) + pad_size) + unencrypted_msg + padding

        encrypted_packet = encryptor.update(packet)
        active_writer.write(encrypted_packet)
        await active_writer.drain()

        if transport_mode == "abridged":
            enc_len = await asyncio.wait_for(active_reader.readexactly(1), timeout=timeout)
            dec_len = decryptor.update(enc_len)
            length = struct.unpack('<B', dec_len)[0]
            if length >= 127:
                enc_more = await asyncio.wait_for(active_reader.readexactly(3), timeout=timeout)
                dec_more = decryptor.update(enc_more)
                length = struct.unpack('<I', dec_more + b'\x00')[0]
            read_len = length << 2
        else:
            enc_len = await asyncio.wait_for(active_reader.readexactly(4), timeout=timeout)
            dec_len = decryptor.update(enc_len)
            length = struct.unpack('<I', dec_len)[0]
            read_len = length

        enc_body = await asyncio.wait_for(active_reader.readexactly(read_len), timeout=timeout)
        dec_body = decryptor.update(enc_body)

        if transport_mode == "randomized_intermediate":
            pad_size = len(dec_body) % 4
            if pad_size > 0:
                dec_body = dec_body[:-pad_size]

        handshake_ms = (time.perf_counter() - handshake_start) * 1000.0

        if len(dec_body) < 20:
            writer.close()
            await writer.wait_closed()
            return "INVALID_RESPONSE", None

        auth_key_id = dec_body[:8]
        res_msg_id = int.from_bytes(dec_body[8:16], 'little')
        res_msg_len = int.from_bytes(dec_body[16:20], 'little')
        res_msg_data = dec_body[20:]

        if auth_key_id != b'\x00' * 8:
            writer.close()
            await writer.wait_closed()
            return "INVALID_RESPONSE", None

        res_pq_constructor = res_msg_data[:4]
        if res_pq_constructor != b'\x63\x24\x16\x05':
            writer.close()
            await writer.wait_closed()
            return "INVALID_RESPONSE", None

        res_nonce = res_msg_data[4:20]
        if res_nonce != nonce:
            writer.close()
            await writer.wait_closed()
            return "INVALID_RESPONSE", None

        writer.close()
        await writer.wait_closed()

        total_ms = (time.perf_counter() - total_start) * 1000.0

        timings = {
            "resolve_ms": round(resolve_ms, 1),
            "connect_ms": round(connect_ms, 1),
            "handshake_ms": round(handshake_ms, 1),
            "total_ms": round(total_ms, 1)
        }

        return "OK", timings

    except asyncio.TimeoutError:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        return "TIMEOUT", None
    except (ConnectionResetError, asyncio.IncompleteReadError) as e:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        return "INVALID_SECRET", None
    except Exception as e:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        return "INVALID_RESPONSE", None


async def check_proxy(
    host: str,
    port: int,
    secret_str: str,
    timeout: float = 10.0,
    dc_id: int = 2,
    debug_log: Optional[Callable[[str], None]] = None
) -> Tuple[str, Optional[Dict[str, float]]]:
    try:
        raw_secret, is_faketls, is_dd, domain = parse_secret(secret_str)
    except ValueError as e:
        if debug_log:
            debug_log(f"Failed to parse secret: {e}")
        return "INVALID_SECRET", None

    if is_faketls:
        return await run_check(host, port, raw_secret, is_faketls, domain, "randomized_intermediate", timeout, dc_id, debug_log)
    elif is_dd:
        return await run_check(host, port, raw_secret, False, None, "randomized_intermediate", timeout, dc_id, debug_log)
    else:
        status, timings = await run_check(host, port, raw_secret, False, None, "abridged", timeout, dc_id, debug_log)
        
        if status in ("CONNECTION_REFUSED", "INVALID_SECRET", "INVALID_RESPONSE"):
            if debug_log:
                debug_log("Abridged check failed/refused. Retrying with Intermediate...")
            status2, timings2 = await run_check(host, port, raw_secret, False, None, "intermediate", timeout, dc_id, debug_log)
            return status2, timings2
            
        return status, timings
