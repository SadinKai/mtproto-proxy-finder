"""
Scraper Provider System for MTProto Proxy Collection.
Fetches proxies from public GitHub repositories, raw text lists, and proxy websites,
normalizing them to a unified format.
"""

import asyncio
import re
import urllib.request
from urllib.parse import urlparse, parse_qs, urlencode
from typing import List, Set, Optional, Callable

# Regular expression matching tg://proxy or https://t.me/proxy URLs
PROXY_REGEX = re.compile(r"(?:tg://proxy\?|https?://t\.me/proxy\?)[^\s\"'<>#]+", re.IGNORECASE)


def normalize_proxy_url(url: str) -> Optional[str]:
    """
    Validates, parses, and normalizes proxy URLs to the standard format:
    https://t.me/proxy?server=SERVER&port=PORT&secret=SECRET
    Returns None if the URL is invalid.
    """
    try:
        # Replace common HTML-encoding characters
        url = url.strip().replace("&amp;", "&")
        if not url:
            return None

        # Parse query parameters
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        if "server" not in query or "port" not in query or "secret" not in query:
            return None

        server = query["server"][0].strip()
        port_str = query["port"][0].strip()
        secret = query["secret"][0].strip()

        if not server or not port_str or not secret:
            return None

        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                return None
        except ValueError:
            return None

        # Clean secret to ensure it contains only hex/base64 compatible characters
        # (remove trailing or leading whitespace, keep hex/base64 characters)
        secret = re.sub(r"[^a-zA-Z0-9+=_/-]", "", secret)
        if not secret:
            return None

        # Reconstruct normalized URL format
        params = {
            "server": server,
            "port": port,
            "secret": secret
        }
        return f"https://t.me/proxy?{urlencode(params)}"
    except Exception:
        return None


async def fetch_http_content(url: str, timeout: float = 10.0) -> str:
    """
    Asynchronously fetches content from an HTTP URL using urllib.request inside
    a thread pool executor to avoid blocking the event loop.
    """
    def sync_fetch():
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="ignore")

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, sync_fetch)


class ProxySource:
    """Base class for all proxy discovery providers."""
    def __init__(self, name: str):
        self.name = name

    async def fetch(self) -> List[str]:
        """Fetches raw proxy URLs from this provider."""
        raise NotImplementedError


class HTTPRawSource(ProxySource):
    """Fetches raw proxy lists or README files via HTTP and extracts matching proxy links."""
    def __init__(self, name: str, url: str):
        super().__init__(name)
        self.url = url

    async def fetch(self) -> List[str]:
        content = await fetch_http_content(self.url, timeout=12.0)
        matches = PROXY_REGEX.findall(content)
        proxies = []
        for match in matches:
            normalized = normalize_proxy_url(match)
            if normalized:
                proxies.append(normalized)
        return proxies


# List of default public proxy sources
DEFAULT_SOURCES = [
    HTTPRawSource(
        "SoliSpirit/mtproto",
        "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt"
    ),
    HTTPRawSource(
        "sunlightcoder/Telegram-MTProto-Proxy",
        "https://raw.githubusercontent.com/sunlightcoder/Telegram-MTProto-Proxy/master/proxies.txt"
    ),
    HTTPRawSource(
        "NimaH79/mtproto-proxies",
        "https://raw.githubusercontent.com/NimaH79/mtproto-proxies/master/README.md"
    ),
    HTTPRawSource(
        "alexbers/mtproxy-collect",
        "https://raw.githubusercontent.com/alexbers/mtproxy-collect/master/proxies.txt"
    ),
    HTTPRawSource(
        "Hookzof/socks5_list",
        "https://raw.githubusercontent.com/Hookzof/socks5_list/master/tg.txt"
    ),
    HTTPRawSource(
        "FediDP/telegram-mtproto-proxy",
        "https://raw.githubusercontent.com/FediDP/telegram-mtproto-proxy/master/proxies.txt"
    ),
    HTTPRawSource(
        "MTPro.XYZ Website",
        "https://mtpro.xyz/"
    ),
]


async def collect_proxies(
    sources: Optional[List[ProxySource]] = None,
    extra_files: Optional[List[str]] = None,
    log_func: Optional[Callable[[str], None]] = None
) -> List[str]:
    """
    Runs all scraper providers concurrently, merges results, validates URLs,
    and removes duplicates.
    """
    if sources is None:
        sources = DEFAULT_SOURCES

    if log_func:
        log_func(f"Starting proxy collection from {len(sources)} public providers...")

    # Fetch from all HTTP sources concurrently
    tasks = [source.fetch() for source in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_urls: Set[str] = set()
    total_found = 0

    # If every single source failed with an Exception, raise a RuntimeError.
    failed_sources_count = sum(1 for res in results if isinstance(res, Exception))
    if len(sources) > 0 and failed_sources_count == len(sources):
        raise RuntimeError("All public proxy sources failed to fetch.")

    for source, res in zip(sources, results):
        if isinstance(res, Exception):
            if log_func:
                log_func(f"Provider '{source.name}' failed with error: {res}")
            continue
        
        provider_proxies = res
        total_found += len(provider_proxies)
        
        # Add to unique set
        for url in provider_proxies:
            all_urls.add(url)

        if log_func:
            log_func(f"Provider '{source.name}': Found {len(provider_proxies)} proxies.")

    # Read from local extra files if supplied
    if extra_files:
        for file_path in extra_files:
            try:
                import os
                if os.path.isfile(file_path):
                    if log_func:
                        log_func(f"Reading extra proxies from local file '{file_path}'...")
                    with open(file_path, "r", encoding="utf-8") as f:
                        count = 0
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                normalized = normalize_proxy_url(line)
                                if normalized:
                                    all_urls.add(normalized)
                                    count += 1
                                    total_found += 1
                        if log_func:
                            log_func(f"File '{file_path}': Found {count} proxies.")
            except Exception as e:
                if log_func:
                    log_func(f"Error reading file '{file_path}': {e}")

    # Remove duplicates by filtering and sorting
    unique_urls = sorted(list(all_urls))

    return unique_urls
