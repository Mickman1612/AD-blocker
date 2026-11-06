"""The local certificates. The key promise: no master key survives setup."""
import pathlib
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest

from proxy import certs

NAMES = ["youtube.com", "*.youtube.com", "www.google.com", "*.twitch.tv", "twitch.tv"]


class CertificateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = pathlib.Path(cls.tmp.name)
        cls.paths = certs.create_certificates(cls.dir, NAMES)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def handshake(self, hostname):
        """A real TLS handshake, verified the way a browser would, using only our root."""
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(self.paths.leaf_cert, self.paths.leaf_key)
        client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client_context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(self.paths.ca_cert.read_bytes()))
        listener = socket.create_server(("127.0.0.1", 0))
        port = listener.getsockname()[1]

        def serve():
            connection, _ = listener.accept()
            try:
                with server_context.wrap_socket(connection, server_side=True) as tls:
                    tls.recv(1)
            except (ssl.SSLError, OSError):
                pass

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
                with client_context.wrap_socket(raw, server_hostname=hostname):
                    return True
        finally:
            thread.join(timeout=5)
            listener.close()

    def test_verifies_for_each_listed_site(self):
        for host in ("youtube.com", "www.youtube.com", "m.youtube.com", "www.google.com", "www.twitch.tv", "twitch.tv"):
            with self.subTest(host):
                self.assertTrue(self.handshake(host))

    def test_is_rejected_for_any_other_site(self):
        for host in ("www.mybank.com", "www.amazon.com", "accounts.google.com", "evilyoutube.com"):
            with self.subTest(host), self.assertRaises(ssl.SSLCertVerificationError):
                self.handshake(host)

    def test_no_master_key_is_left_on_disk(self):
        files = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(files, ["ca.cer", "leaf.key", "leaf.pem"])
        self.assertIn(b"PRIVATE KEY", self.paths.leaf_key.read_bytes())
        self.assertNotIn(b"PRIVATE KEY", self.paths.leaf_cert.read_bytes())
        self.assertNotIn(b"PRIVATE KEY", self.paths.ca_cert.read_bytes())

    def test_the_only_key_on_disk_cannot_issue_certificates(self):
        decoded = ssl._ssl._test_decode_cert(str(self.paths.leaf_cert))
        self.assertEqual(sorted(name for kind, name in decoded["subjectAltName"]), sorted(NAMES))
        dump = subprocess.run(["certutil", "-dump", str(self.paths.leaf_cert)],
                              capture_output=True, text=True, timeout=30).stdout
        self.assertIn("Subject Type=End Entity", dump)

    def test_root_is_limited_to_the_listed_sites(self):
        dump = subprocess.run(["certutil", "-dump", str(self.paths.ca_cert)],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(dump.returncode, 0, dump.stdout)
        self.assertIn("Local Ad Blocker Root", dump.stdout)
        self.assertIn("Name Constraints", dump.stdout)
        self.assertIn("Permitted", dump.stdout)
        self.assertIn("youtube.com", dump.stdout)
        self.assertIn("Subject Type=CA", dump.stdout)

    def test_two_runs_make_different_keys(self):
        with tempfile.TemporaryDirectory() as other:
            second = certs.create_certificates(pathlib.Path(other), NAMES)
            self.assertNotEqual(second.leaf_key.read_bytes(), self.paths.leaf_key.read_bytes())
            self.assertNotEqual(second.ca_cert.read_bytes(), self.paths.ca_cert.read_bytes())

    def test_keys_are_strong_enough_for_browsers(self):
        self.assertGreaterEqual(certs.KEY_BITS, 2048)


if __name__ == "__main__":
    unittest.main()
