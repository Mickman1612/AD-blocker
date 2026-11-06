"""The filtering app, against a fake upstream site, so everything runs offline on this PC."""
import asyncio
import gzip
import hashlib
import base64
import pathlib
import socket
import ssl
import tempfile
import threading
import unittest

from proxy import certs
from proxy.server import ProxyConfig, ProxyServer, inject_into_html, patch_csp, build_pac

UPSTREAM_HOST = "www.youtube.com"
SNIPPET = b"<style>.x{}</style><script>window.injected=1</script>"


class FakeUpstream:
    """A small TLS server on loopback whose replies each test chooses."""

    def __init__(self, tls_context):
        self.tls_context = tls_context
        self.replies = {}
        self.requests = []
        self.server = None
        self.port = None

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0, ssl=self.tls_context)
        self.port = self.server.sockets[0].getsockname()[1]

    async def handle(self, reader, writer):
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head.decode("latin-1").split("\r\n")
                method, target, _ = lines[0].split(" ", 2)
                headers = {l.split(":", 1)[0].lower(): l.split(":", 1)[1].strip() for l in lines[1:] if ":" in l}
                body = b""
                if "content-length" in headers:
                    body = await reader.readexactly(int(headers["content-length"]))
                elif headers.get("transfer-encoding", "").lower() == "chunked":
                    while True:
                        size = int((await reader.readline()).strip(), 16)
                        data = await reader.readexactly(size + 2)
                        if size == 0:
                            break
                        body += data[:-2]
                self.requests.append({"method": method, "target": target, "headers": headers, "body": body})
                reply = self.replies.get(target, b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                if callable(reply):
                    await reply(reader, writer)
                    return
                writer.write(reply)
                await writer.drain()
                if b"connection: close" in reply.lower().split(b"\r\n\r\n")[0]:
                    break
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()


def response(body=b"", status="200 OK", headers=()):
    head = [f"HTTP/1.1 {status}"] + list(headers)
    if not any(h.lower().startswith(("content-length", "transfer-encoding")) for h in headers):
        head.append(f"Content-Length: {len(body)}")
    return ("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + body


def chunked(*parts):
    return b"".join(b"%x\r\n%s\r\n" % (len(p), p) for p in parts) + b"0\r\n\r\n"


class ProxyTestCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        directory = pathlib.Path(cls.tmp.name)
        cls.paths = certs.create_certificates(directory, ["youtube.com", "*.youtube.com", "upstream.test"])
        cls.ca_pem = ssl.DER_cert_to_PEM_cert(cls.paths.ca_cert.read_bytes())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    async def asyncSetUp(self):
        upstream_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        upstream_tls.load_cert_chain(self.paths.leaf_cert, self.paths.leaf_key)
        self.upstream = FakeUpstream(upstream_tls)
        await self.upstream.start()
        upstream_client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        upstream_client.load_verify_locations(cadata=self.ca_pem)
        self.config = ProxyConfig(
            port=0,
            cert_file=str(self.paths.leaf_cert),
            key_file=str(self.paths.leaf_key),
            decrypt_domains={"youtube.com"},
            decrypt_hosts=set(),
            block_domains={"doubleclick.net", "ads.youtube.com"},
            exempt_hosts={"static.doubleclick.net"},
            ad_path_patterns=[r"^https?://([^/]*\.)?youtube\.com/pagead/"],
            upstream_tls=upstream_client,
            resolve=lambda host, port: ("127.0.0.1", self.upstream.port) if host.endswith("youtube.com") else (host, port),
            page_snippet=lambda host: (SNIPPET, "scripthash", "stylehash"),
        )
        self.proxy = ProxyServer(self.config)
        await self.proxy.start()
        self.addAsyncCleanup(self.proxy.stop)
        self.client_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.client_tls.load_verify_locations(cadata=self.ca_pem)

    async def connect_tunnel(self, host=UPSTREAM_HOST):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.proxy.port)
        writer.write(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode())
        await writer.drain()
        status = await reader.readuntil(b"\r\n\r\n")
        return reader, writer, status

    async def open_decrypted(self):
        reader, writer, status = await self.connect_tunnel()
        self.assertIn(b"200", status)
        await writer.start_tls(self.client_tls, server_hostname=UPSTREAM_HOST)
        return reader, writer

    async def fetch(self, reader, writer, target="/", extra=(), method="GET", body=b""):
        lines = [f"{method} {target} HTTP/1.1", f"Host: {UPSTREAM_HOST}", *extra]
        if body:
            lines.append(f"Content-Length: {len(body)}")
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
        await writer.drain()
        head = (await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)).decode("latin-1")
        headers = {l.split(":", 1)[0].lower(): l.split(":", 1)[1].strip() for l in head.split("\r\n")[1:] if ":" in l}
        data = b""
        if method == "HEAD" or " 304 " in head.split("\r\n")[0] or " 204 " in head.split("\r\n")[0]:
            return head, headers, data
        if "content-length" in headers:
            data = await asyncio.wait_for(reader.readexactly(int(headers["content-length"])), 5)
        elif headers.get("transfer-encoding", "").lower() == "chunked":
            while True:
                size = int((await asyncio.wait_for(reader.readline(), 5)).strip(), 16)
                chunk = await reader.readexactly(size + 2)
                if size == 0:
                    break
                data += chunk[:-2]
        return head, headers, data


class TunnelTests(ProxyTestCase):
    async def test_ad_hosts_are_refused(self):
        for host in ("doubleclick.net", "securepubads.g.doubleclick.net", "ads.youtube.com"):
            with self.subTest(host):
                _, writer, status = await self.connect_tunnel(host)
                self.assertIn(b"403", status)
                writer.close()

    async def test_other_sites_tunnel_without_being_decrypted(self):
        async def echo(reader, writer):
            writer.write(await reader.read(100))
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        self.config.resolve = lambda host, _: (host, port)
        reader, writer, status = await self.connect_tunnel("127.0.0.1")
        self.assertIn(b"200", status)
        writer.write(b"bytes the app must not touch")
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.read(100), 5), b"bytes the app must not touch")
        writer.close()
        server.close()

    async def test_listens_on_this_pc_only(self):
        self.assertEqual(self.proxy.bound_address, "127.0.0.1")

    async def test_serves_its_routing_file(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.proxy.port)
        writer.write(b"GET /proxy.pac HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(100000), 5)
        self.assertIn(b"FindProxyForURL", data)
        writer.close()


class DecryptedTrafficTests(ProxyTestCase):
    async def test_page_gets_our_scripts(self):
        self.upstream.replies["/watch"] = response(b"<html><head><title>t</title></head><body>hi</body></html>",
                                                   headers=["Content-Type: text/html; charset=utf-8"])
        reader, writer = await self.open_decrypted()
        head, headers, body = await self.fetch(reader, writer, "/watch", ["Sec-Fetch-Dest: document"])
        self.assertTrue(body.startswith(b"<html><head>" + SNIPPET + b"<title>"), body[:90])
        self.assertEqual(int(headers["content-length"]), len(body))
        writer.close()

    async def test_gzipped_page_is_handled(self):
        page = b"<html><head></head><body>hi</body></html>"
        self.upstream.replies["/gz"] = response(gzip.compress(page), headers=[
            "Content-Type: text/html", "Content-Encoding: gzip"])
        reader, writer = await self.open_decrypted()
        _, headers, body = await self.fetch(reader, writer, "/gz", ["Sec-Fetch-Dest: document"])
        self.assertNotIn("content-encoding", headers)
        self.assertIn(SNIPPET, body)
        writer.close()

    async def test_chunked_page_is_handled(self):
        self.upstream.replies["/chunked"] = response(chunked(b"<html><he", b"ad></head>hi</html>"), headers=[
            "Content-Type: text/html", "Transfer-Encoding: chunked"])
        reader, writer = await self.open_decrypted()
        _, headers, body = await self.fetch(reader, writer, "/chunked", ["Sec-Fetch-Dest: document"])
        self.assertIn(SNIPPET, body)
        self.assertNotIn("transfer-encoding", headers)
        writer.close()

    async def test_everything_else_passes_through_unchanged(self):
        data = bytes(range(256)) * 400
        self.upstream.replies["/data.bin"] = response(data, headers=["Content-Type: application/octet-stream"])
        self.upstream.replies["/api"] = response(b'{"adPlacements":[1]}', headers=["Content-Type: application/json"])
        reader, writer = await self.open_decrypted()
        self.assertEqual((await self.fetch(reader, writer, "/data.bin"))[2], data)
        self.assertEqual((await self.fetch(reader, writer, "/api"))[2], b'{"adPlacements":[1]}')
        writer.close()

    async def test_chunked_data_passes_through(self):
        self.upstream.replies["/c"] = response(chunked(b"abc", b"def"), headers=[
            "Content-Type: text/plain", "Transfer-Encoding: chunked"])
        reader, writer = await self.open_decrypted()
        self.assertEqual((await self.fetch(reader, writer, "/c"))[2], b"abcdef")
        writer.close()

    async def test_html_for_scripts_is_not_injected(self):
        self.upstream.replies["/frag"] = response(b"<head></head>", headers=["Content-Type: text/html"])
        reader, writer = await self.open_decrypted()
        _, _, body = await self.fetch(reader, writer, "/frag", ["Sec-Fetch-Dest: empty"])
        self.assertEqual(body, b"<head></head>")
        writer.close()

    async def test_ad_paths_get_an_empty_answer_without_contacting_the_site(self):
        reader, writer = await self.open_decrypted()
        head, _, _ = await self.fetch(reader, writer, "/pagead/viewthroughconversion/1")
        self.assertIn(" 204 ", head)
        self.assertEqual(self.upstream.requests, [])
        writer.close()

    async def test_request_bodies_and_headers_reach_the_site(self):
        self.upstream.replies["/post"] = response(b"ok", headers=["Content-Type: text/plain"])
        reader, writer = await self.open_decrypted()
        await self.fetch(reader, writer, "/post", ["Cookie: a=1", "Accept-Encoding: gzip, br, zstd"], "POST", b"payload")
        request = self.upstream.requests[-1]
        self.assertEqual(request["body"], b"payload")
        self.assertEqual(request["headers"]["cookie"], "a=1")
        self.assertEqual(request["headers"]["accept-encoding"], "gzip")
        writer.close()

    async def test_chunked_request_bodies_reach_the_site(self):
        self.upstream.replies["/up"] = response(b"ok", headers=["Content-Type: text/plain"])
        reader, writer = await self.open_decrypted()
        writer.write(f"POST /up HTTP/1.1\r\nHost: {UPSTREAM_HOST}\r\nTransfer-Encoding: chunked\r\n\r\n".encode()
                     + chunked(b"pay", b"load"))
        await writer.drain()
        await asyncio.wait_for(reader.readuntil(b"ok"), 5)
        self.assertEqual(self.upstream.requests[-1]["body"], b"payload")
        writer.close()

    async def test_one_connection_carries_several_requests(self):
        self.upstream.replies["/a"] = response(b"A", headers=["Content-Type: text/plain"])
        self.upstream.replies["/b"] = response(b"B", headers=["Content-Type: text/plain"])
        reader, writer = await self.open_decrypted()
        self.assertEqual((await self.fetch(reader, writer, "/a"))[2], b"A")
        self.assertEqual((await self.fetch(reader, writer, "/b"))[2], b"B")
        writer.close()

    async def test_responses_without_a_body_stay_without_one(self):
        self.upstream.replies["/nm"] = b"HTTP/1.1 304 Not Modified\r\nETag: x\r\n\r\n"
        self.upstream.replies["/after"] = response(b"next", headers=["Content-Type: text/plain"])
        reader, writer = await self.open_decrypted()
        head, _, _ = await self.fetch(reader, writer, "/nm")
        self.assertIn(" 304 ", head)
        self.assertEqual((await self.fetch(reader, writer, "/after"))[2], b"next")
        writer.close()

    async def test_response_ending_at_connection_close_is_delivered(self):
        self.upstream.replies["/close"] = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nall of it"
        reader, writer = await self.open_decrypted()
        writer.write(f"GET /close HTTP/1.1\r\nHost: {UPSTREAM_HOST}\r\n\r\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(-1), 5)
        self.assertTrue(data.endswith(b"all of it"), data)
        writer.close()

    async def test_websockets_keep_working(self):
        async def upgrade(reader, writer):
            writer.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
            await writer.drain()
            writer.write(await reader.read(100))
            await writer.drain()
            writer.close()

        self.upstream.replies["/ws"] = upgrade
        reader, writer = await self.open_decrypted()
        writer.write(f"GET /ws HTTP/1.1\r\nHost: {UPSTREAM_HOST}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n".encode())
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        self.assertIn(b" 101 ", head)
        writer.write(b"ping")
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.read(100), 5), b"ping")
        writer.close()

    async def test_an_unreachable_site_gives_a_clean_error(self):
        self.config.resolve = lambda host, port: ("127.0.0.1", 1)
        reader, writer = await self.open_decrypted()
        head, _, _ = await self.fetch(reader, writer, "/x")
        self.assertIn(" 502 ", head)
        writer.close()

    async def test_a_site_with_an_invalid_certificate_is_refused(self):
        self.config.upstream_tls = ssl.create_default_context()  # Doesn't trust the fake site.
        self.upstream.replies["/x"] = response(b"secret")
        reader, writer = await self.open_decrypted()
        head, _, body = await self.fetch(reader, writer, "/x")
        self.assertIn(" 502 ", head)
        self.assertNotIn(b"secret", body)
        writer.close()


class PageEditingTests(unittest.TestCase):
    def test_goes_right_after_the_head_tag(self):
        self.assertEqual(inject_into_html(b'<!doctype html><html><head lang="x"><a>', b"<s>"),
                         b'<!doctype html><html><head lang="x"><s><a>')

    def test_head_tag_case_does_not_matter(self):
        self.assertEqual(inject_into_html(b"<HEAD><a>", b"<s>"), b"<HEAD><s><a>")

    def test_page_with_no_head_gets_it_at_the_start(self):
        self.assertEqual(inject_into_html(b"<p>hi", b"<s>"), b"<s><p>hi")

    def test_doesnt_match_header_tags(self):
        self.assertEqual(inject_into_html(b"<header>x</header><head>y", b"<s>"), b"<header>x</header><head><s>y")


class SecurityPolicyTests(unittest.TestCase):
    def test_adds_hashes_to_a_strict_policy(self):
        result = patch_csp("script-src 'self' 'nonce-abc'; style-src 'self'", "SH", "ST")
        self.assertIn("script-src 'self' 'nonce-abc' 'sha256-SH'", result)
        self.assertIn("style-src 'self' 'sha256-ST'", result)

    def test_leaves_unsafe_inline_alone_because_a_hash_would_turn_it_off(self):
        policy = "script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'"
        self.assertEqual(patch_csp(policy, "SH", "ST"), policy)

    def test_uses_default_src_when_that_is_all_there_is(self):
        result = patch_csp("default-src 'self'", "SH", "ST")
        self.assertIn("default-src 'self'", result)
        self.assertIn("script-src 'self' 'sha256-SH'", result)
        self.assertIn("style-src 'self' 'sha256-ST'", result)

    def test_replaces_none(self):
        self.assertIn("script-src 'sha256-SH'", patch_csp("script-src 'none'", "SH", "ST"))

    def test_policy_without_those_rules_is_unchanged(self):
        self.assertEqual(patch_csp("frame-ancestors 'self'", "SH", "ST"), "frame-ancestors 'self'")

    def test_unsafe_inline_with_a_nonce_still_gets_a_hash(self):
        self.assertIn("'sha256-SH'", patch_csp("script-src 'unsafe-inline' 'nonce-a'", "SH", "ST"))


class RoutingFileTests(unittest.TestCase):
    PAC = build_pac(8899, {"doubleclick.net"}, {"static.doubleclick.net"}, {"youtube.com"}, {"www.google.com"})

    def test_mentions_each_rule_and_has_a_fallback(self):
        for text in ("doubleclick.net", "static.doubleclick.net", "youtube.com", "www.google.com",
                     "PROXY 127.0.0.1:8899; DIRECT", "DIRECT"):
            self.assertIn(text, self.PAC)


if __name__ == "__main__":
    unittest.main()
