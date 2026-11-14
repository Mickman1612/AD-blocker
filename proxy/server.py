"""The filtering app. It listens on this PC only, stores nothing and logs nothing.

Only listed sites and ad domains are sent here by the routing file. For ad domains it refuses the
connection. For listed sites it decrypts, adds our page scripts to HTML pages and answers known ad
paths with nothing. All other traffic that reaches it passes through without being decrypted.
"""
import asyncio
import base64
import dataclasses
import hashlib
import json
import re
import ssl
import typing
import zlib

READ_LIMIT = 1 << 20
CHUNK = 1 << 16
INJECT_SEARCH_BYTES = 1 << 16  # How far into a page to look for its head tag.
MAX_BUFFERED_REQUEST = 8 << 20
CONNECT_TIMEOUT = 15
INJECT_DESTINATIONS = {"document", "iframe", "frame"}
NETWORK_ERRORS = (ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                  ssl.SSLError, OSError, TimeoutError, ValueError)

_HEAD_TAG = re.compile(rb"<head(?:\s[^>]*)?>", re.I)
_DOCTYPE = re.compile(rb"^\s*<!doctype[^>]*>", re.I)


@dataclasses.dataclass
class ProxyConfig:
    port: int
    cert_file: str
    key_file: str
    decrypt_domains: set
    decrypt_hosts: set
    block_domains: set
    exempt_hosts: set
    ad_path_patterns: list
    upstream_tls: typing.Optional[ssl.SSLContext] = None
    resolve: typing.Callable = lambda host, port: (host, port)
    page_snippet: typing.Optional[typing.Callable] = None


def matches_domain(host, domains):
    """True if the host is a listed domain or a subdomain of one."""
    while host:
        if host in domains:
            return True
        _, _, host = host.partition(".")
    return False


def inject_into_html(page, snippet):
    head = _HEAD_TAG.search(page, 0, 1 << 16)
    if head:
        return page[:head.end()] + snippet + page[head.end():]
    doctype = _DOCTYPE.search(page)
    if doctype:  # Anything before the doctype would change how the whole page lays out.
        return page[:doctype.end()] + snippet + page[doctype.end():]
    return snippet + page


def patch_csp(policy, script_hash, style_hash):
    """Allow only our exact inline code. Adding a hash next to 'unsafe-inline' would switch that
    off for the page's own code, so a policy already allowing inline code is left alone."""
    directives = [part.strip() for part in policy.split(";") if part.strip()]
    tokens = {directive.split()[0].lower(): directive.split()[1:] for directive in directives}

    def needs_hash(sources):
        lowered = [source.lower() for source in sources]
        allows_inline = "'unsafe-inline'" in lowered
        inline_disabled = any(source.startswith(("'nonce-", "'sha256-", "'sha384-", "'sha512-")) for source in lowered)
        return not allows_inline or inline_disabled

    def with_hash(sources, value):
        return [source for source in sources if source.lower() != "'none'"] + [f"'sha256-{value}'"]

    changes = {}
    additions = []
    for names, value in ((("script-src", "script-src-elem"), script_hash), (("style-src", "style-src-elem"), style_hash)):
        present = [name for name in names if name in tokens]
        for name in present:
            if needs_hash(tokens[name]):
                changes[name] = with_hash(tokens[name], value)
        if not present and "default-src" in tokens and needs_hash(tokens["default-src"]):
            additions.append(" ".join([names[0], *with_hash(tokens["default-src"], value)]))

    result = []
    for directive in directives:
        name = directive.split()[0].lower()
        result.append(" ".join([directive.split()[0], *changes[name]]) if name in changes else directive)
    return "; ".join(result + additions)


def build_pac(port, block_domains, exempt_hosts, decrypt_domains, decrypt_hosts=()):
    """The routing file. Everything not listed connects directly and never reaches the app.
    The fallback keeps listed sites working if the app isn't running."""
    def table(names):
        return json.dumps({name: 1 for name in sorted(names)}, separators=(",", ":"))

    return (
        f"var BLOCK={table(block_domains)},EXEMPT={table(exempt_hosts)},"
        f"DOMAINS={table(decrypt_domains)},HOSTS={table(decrypt_hosts)};\n"
        "function listed(table,host){for(;;){if(table[host]===1)return true;"
        'var dot=host.indexOf(".");if(dot<0)return false;host=host.slice(dot+1);}}\n'
        "function FindProxyForURL(url,host){host=host.toLowerCase();"
        'if(EXEMPT[host]===1)return "DIRECT";'
        f'if(listed(BLOCK,host))return "PROXY 127.0.0.1:{port}";'
        f'if(HOSTS[host]===1||listed(DOMAINS,host))return "PROXY 127.0.0.1:{port}; DIRECT";'
        'return "DIRECT";}\n'
    )


# --- HTTP helpers ---

async def _read_head(reader):
    try:
        return await reader.readuntil(b"\r\n\r\n")
    except asyncio.IncompleteReadError as error:
        if error.partial:
            raise
        return None


def _parse_head(head):
    lines = head.decode("latin-1").split("\r\n")
    fields = [tuple(part.strip() for part in line.split(":", 1)) for line in lines[1:] if ":" in line]
    return lines[0], fields


def _field(fields, name):
    for key, value in fields:
        if key.lower() == name:
            return value
    return None


def _without(fields, *names):
    return [(key, value) for key, value in fields if key.lower() not in names]


def _build_head(start_line, fields):
    lines = [start_line] + [f"{key}: {value}" for key, value in fields]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


def _is_chunked(fields):
    return "chunked" in (_field(fields, "transfer-encoding") or "").lower()


async def _read_chunked(reader):
    parts = []
    while True:
        size = int((await reader.readline()).split(b";")[0].strip() or b"0", 16)
        if size == 0:
            while (await reader.readline()).strip():
                pass
            return b"".join(parts)
        parts.append(await reader.readexactly(size))
        await reader.readexactly(2)


def _chunk(data):
    return b"%x\r\n%s\r\n" % (len(data), data) if data else b""


async def _body_pieces(reader, chunked, length):
    """The response body as it arrives, without its transfer framing."""
    if chunked:
        while True:
            size = int((await reader.readline()).split(b";")[0].strip() or b"0", 16)
            if size == 0:
                while (await reader.readline()).strip():
                    pass
                return
            remaining = size
            while remaining:
                data = await reader.read(min(remaining, CHUNK))
                if not data:
                    raise ConnectionError("connection ended early")
                remaining -= len(data)
                yield data
            await reader.readexactly(2)
    elif length is not None:
        remaining = int(length)
        while remaining:
            data = await reader.read(min(remaining, CHUNK))
            if not data:
                raise ConnectionError("connection ended early")
            remaining -= len(data)
            yield data
    else:
        while data := await reader.read(CHUNK):
            yield data


async def _relay_exact(reader, writer, remaining):
    while remaining:
        data = await reader.read(min(remaining, CHUNK))
        if not data:
            raise ConnectionError("connection ended early")
        writer.write(data)
        await writer.drain()
        remaining -= len(data)


async def _relay_chunked(reader, writer):
    """Copy a chunked body exactly as it arrives, so it keeps streaming."""
    while True:
        line = await reader.readline()
        if not line:
            raise ConnectionError("connection ended early")
        writer.write(line)
        size = int(line.split(b";")[0].strip() or b"0", 16)
        if size == 0:
            while True:
                trailer = await reader.readline()
                writer.write(trailer)
                if not trailer.strip():
                    await writer.drain()
                    return
        await _relay_exact(reader, writer, size + 2)


async def _relay_until_close(reader, writer):
    while data := await reader.read(CHUNK):
        writer.write(data)
        await writer.drain()


async def _pipe(reader, writer):
    try:
        await _relay_until_close(reader, writer)
    except NETWORK_ERRORS:
        pass


async def _pipe_both_ways(reader_a, writer_a, reader_b, writer_b):
    tasks = [asyncio.create_task(_pipe(reader_a, writer_b)), asyncio.create_task(_pipe(reader_b, writer_a))]
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _close(writer):
    if writer is not None:
        try:
            writer.close()
        except NETWORK_ERRORS:
            pass


def _simple_response(status, body=b"", content_type="text/plain", close=False):
    head = [f"HTTP/1.1 {status}", f"Content-Type: {content_type}", f"Content-Length: {len(body)}",
            "Access-Control-Allow-Origin: *"]
    if close:
        head.append("Connection: close")
    return ("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + body


class ProxyServer:
    def __init__(self, config):
        self.config = config
        self.port = None
        self.bound_address = "127.0.0.1"
        self._server = None
        self._tasks = set()
        self._client_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._client_tls.load_cert_chain(config.cert_file, config.key_file)
        self._client_tls.set_alpn_protocols(["http/1.1"])
        self._ad_paths = [re.compile(pattern, re.I) for pattern in config.ad_path_patterns]
        self._default_upstream_tls = ssl.create_default_context()

    async def start(self):
        self._server = await asyncio.start_server(self._on_client, self.bound_address, self.config.port, limit=READ_LIMIT)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self):
        self._server.close()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(self._server.wait_closed(), 2)
        except TimeoutError:
            pass

    async def serve_forever(self):
        await self._server.serve_forever()

    def pac(self):
        return build_pac(self.port, self.config.block_domains, self.config.exempt_hosts,
                         self.config.decrypt_domains, self.config.decrypt_hosts)

    def _is_blocked(self, host):
        return host not in self.config.exempt_hosts and matches_domain(host, self.config.block_domains)

    def _is_decrypted(self, host):
        return host in self.config.decrypt_hosts or matches_domain(host, self.config.decrypt_domains)

    async def _on_client(self, reader, writer):
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            head = await _read_head(reader)
            if head is None:
                return
            start_line, fields = _parse_head(head)
            method, target, _ = start_line.split(" ", 2)
            if method == "CONNECT":
                await self._on_connect(target, reader, writer)
            elif target.startswith("/"):
                await self._on_local(target, writer)
            else:
                await self._on_plain_http(method, target, fields, reader, writer)
        except NETWORK_ERRORS:
            pass
        finally:
            self._tasks.discard(task)
            _close(writer)

    async def _on_local(self, target, writer):
        path = target.split("?", 1)[0]
        if path == "/proxy.pac":
            writer.write(_simple_response("200 OK", self.pac().encode(), "application/x-ns-proxy-autoconfig", close=True))
        elif path == "/healthz":
            writer.write(_simple_response("200 OK", b"Local Ad Blocker", close=True))
        else:
            writer.write(_simple_response("404 Not Found", close=True))
        await writer.drain()

    async def _on_connect(self, target, reader, writer):
        host, _, port_text = target.rpartition(":")
        host, port = host.strip("[]").lower(), int(port_text)
        if self._is_blocked(host):
            writer.write(b"HTTP/1.1 403 Blocked\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return
        if self._is_decrypted(host) and port == 443:
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await writer.start_tls(self._client_tls)
            await self._serve_decrypted(host, reader, writer)
            return
        address = self.config.resolve(host, port)
        upstream_reader, upstream_writer = await asyncio.wait_for(asyncio.open_connection(*address), CONNECT_TIMEOUT)
        try:
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await _pipe_both_ways(reader, writer, upstream_reader, upstream_writer)
        finally:
            _close(upstream_writer)

    async def _on_plain_http(self, method, target, fields, reader, writer):
        match = re.match(r"^http://([^/:]+)(?::(\d+))?(/.*)?$", target, re.I)
        if not match:
            writer.write(_simple_response("400 Bad Request", close=True))
            await writer.drain()
            return
        host, port, path = match.group(1).lower(), int(match.group(2) or 80), match.group(3) or "/"
        if self._is_blocked(host):
            writer.write(_simple_response("403 Blocked", close=True))
            await writer.drain()
            return
        address = self.config.resolve(host, port)
        upstream_reader, upstream_writer = await asyncio.wait_for(asyncio.open_connection(*address), CONNECT_TIMEOUT)
        try:
            kept = _without(fields, "proxy-connection", "connection") + [("Connection", "close")]
            upstream_writer.write(_build_head(f"{method} {path} HTTP/1.1", kept))
            await upstream_writer.drain()
            await _pipe_both_ways(reader, writer, upstream_reader, upstream_writer)
        finally:
            _close(upstream_writer)

    async def _open_upstream(self, host):
        address = self.config.resolve(host, 443)
        context = self.config.upstream_tls or self._default_upstream_tls
        context.set_alpn_protocols(["http/1.1"])
        return await asyncio.wait_for(
            asyncio.open_connection(*address, ssl=context, server_hostname=host, limit=READ_LIMIT), CONNECT_TIMEOUT)

    async def _read_request_body(self, reader, fields):
        """Returns (body, length to stream). Small bodies are held so a stale connection can be retried."""
        if _is_chunked(fields):
            return await _read_chunked(reader), 0
        length = int(_field(fields, "content-length") or 0)
        if length > MAX_BUFFERED_REQUEST:
            return None, length
        return (await reader.readexactly(length) if length else b""), 0

    async def _serve_decrypted(self, host, reader, writer):
        upstream = None
        try:
            while True:
                head = await _read_head(reader)
                if head is None:
                    return
                start_line, fields = _parse_head(head)
                method, target, _ = start_line.split(" ", 2)
                body, stream_length = await self._read_request_body(reader, fields)

                if any(pattern.search(f"https://{host}{target}") for pattern in self._ad_paths):
                    writer.write(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nAccess-Control-Allow-Origin: *\r\n\r\n")
                    await writer.drain()
                    continue

                outgoing = _without(fields, "proxy-connection")
                if _is_chunked(fields):
                    outgoing = _without(outgoing, "transfer-encoding") + [("Content-Length", str(len(body)))]
                if _field(outgoing, "accept-encoding") is not None:
                    # We can only reopen gzip with the standard library.
                    outgoing = _without(outgoing, "accept-encoding") + [("Accept-Encoding", "gzip")]
                request_head = _build_head(start_line, outgoing)

                upstream, response_head = await self._send_request(
                    host, upstream, request_head, body, stream_length, reader, writer)
                if response_head is None:
                    return

                upgraded, keep_open = await self._send_response(
                    host, method, fields, response_head, upstream, reader, writer)
                if upgraded:
                    return
                if not keep_open:
                    _close(upstream[1])
                    upstream = None
                if (_field(fields, "connection") or "").lower() == "close":
                    return
        finally:
            if upstream is not None:
                _close(upstream[1])

    async def _send_request(self, host, upstream, request_head, body, stream_length, reader, writer):
        """Send the request, retrying once on a new connection if a reused one had gone stale."""
        reused = upstream is not None
        for attempt in range(2):
            try:
                if upstream is None:
                    upstream = await self._open_upstream(host)
                upstream_reader, upstream_writer = upstream
                upstream_writer.write(request_head)
                if body:
                    upstream_writer.write(body)
                await upstream_writer.drain()
                if stream_length:
                    await _relay_exact(reader, upstream_writer, stream_length)
                response_head = await _read_head(upstream_reader)
                while response_head is not None:
                    status_line, _ = _parse_head(response_head)
                    code = status_line.split(" ", 2)[1]
                    if code.startswith("1") and code != "101":
                        writer.write(response_head)  # Interim answers, such as early hints.
                        await writer.drain()
                        response_head = await _read_head(upstream_reader)
                        continue
                    break
                if response_head is None:
                    raise ConnectionError("no response")
                return upstream, response_head
            except NETWORK_ERRORS:
                if upstream is not None:
                    _close(upstream[1])
                    upstream = None
                if not reused or attempt == 1 or stream_length:
                    break
        writer.write(_simple_response("502 Bad Gateway", b"Local Ad Blocker couldn't reach this site.", close=True))
        await writer.drain()
        return None, None

    async def _send_response(self, host, method, request_fields, response_head, upstream, reader, writer):
        """Returns (upgraded, upstream connection can be reused)."""
        upstream_reader, upstream_writer = upstream
        status_line, fields = _parse_head(response_head)
        code = status_line.split(" ", 2)[1]

        if code == "101":
            writer.write(response_head)
            await writer.drain()
            await _pipe_both_ways(reader, writer, upstream_reader, upstream_writer)
            return True, False

        closing = (_field(fields, "connection") or "").lower() == "close" or status_line.startswith("HTTP/1.0")

        if method == "HEAD" or code in ("204", "304"):
            writer.write(response_head)
            await writer.drain()
            return False, not closing

        chunked = _is_chunked(fields)
        length = _field(fields, "content-length")

        if self._wants_injection(method, code, request_fields, fields):
            pieces = _body_pieces(upstream_reader, chunked, length)
            await self._stream_injected(host, status_line, fields, pieces, writer)
            # A body that ends when the connection closes leaves nothing to reuse.
            return False, not closing and (chunked or length is not None)

        writer.write(response_head)
        await writer.drain()
        if chunked:
            await _relay_chunked(upstream_reader, writer)
        elif length is not None:
            await _relay_exact(upstream_reader, writer, int(length))
        else:
            await _relay_until_close(upstream_reader, writer)
            await writer.drain()
            writer.close()
            return False, False
        return False, not closing

    def _wants_injection(self, method, code, request_fields, fields):
        if self.config.page_snippet is None or method != "GET" or code != "200":
            return False
        if (_field(request_fields, "sec-fetch-dest") or "").lower() not in INJECT_DESTINATIONS:
            return False
        if "text/html" not in (_field(fields, "content-type") or "").lower():
            return False
        return (_field(fields, "content-encoding") or "identity").lower() in ("identity", "gzip", "x-gzip", "deflate")

    async def _stream_injected(self, host, status_line, fields, pieces, writer):
        """Pass the page on as it arrives, adding our scripts once the head tag has been seen.
        Holding the whole page back first delayed YouTube's first paint by over a second."""
        encoding = (_field(fields, "content-encoding") or "identity").lower()
        decoder = None
        if encoding in ("gzip", "x-gzip"):
            decoder = zlib.decompressobj(wbits=31)
        elif encoding == "deflate":
            decoder = zlib.decompressobj()
        code, script_hash, style_hash = self.config.page_snippet(host)

        kept = _without(fields, "transfer-encoding", "content-length", "content-encoding", "content-security-policy")
        for key, value in fields:
            if key.lower() == "content-security-policy":
                kept.append((key, patch_csp(value, script_hash, style_hash)))
        kept.append(("Transfer-Encoding", "chunked"))

        head_sent = injected = False
        pending = b""
        async for raw in pieces:
            try:
                data = decoder.decompress(raw) if decoder else raw
            except zlib.error:
                if head_sent:
                    raise ConnectionError("page stopped decoding part-way")
                await self._pass_through(status_line, fields, raw, pieces, writer)
                return
            if not head_sent:
                writer.write(_build_head(status_line, kept))
                head_sent = True
            if injected:
                writer.write(_chunk(data))
            else:
                pending += data
                if _HEAD_TAG.search(pending) or len(pending) >= INJECT_SEARCH_BYTES:
                    writer.write(_chunk(inject_into_html(pending, code)))
                    pending, injected = b"", True
            await writer.drain()

        tail = decoder.flush() if decoder else b""
        if not head_sent:
            writer.write(_build_head(status_line, kept))
        writer.write(_chunk(tail) if injected else _chunk(inject_into_html(pending + tail, code)))
        writer.write(b"0\r\n\r\n")
        await writer.drain()

    async def _pass_through(self, status_line, fields, first, pieces, writer):
        """The page couldn't be decoded, so send it on exactly as the site sent it."""
        writer.write(_build_head(status_line, _without(fields, "transfer-encoding", "content-length")
                                 + [("Transfer-Encoding", "chunked")]))
        writer.write(_chunk(first))
        async for raw in pieces:
            writer.write(_chunk(raw))
            await writer.drain()
        writer.write(b"0\r\n\r\n")
        await writer.drain()


def inline_hash(text):
    """The hash a security policy uses to allow one exact inline script or style."""
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode()
