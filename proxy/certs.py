"""Makes the local certificates using only the standard library.

One run creates a root certificate, uses its key once to sign a certificate for the listed sites,
then lets that key go without ever writing it to disk. Nothing can issue another certificate
afterwards, so the root can't vouch for a bank or anything else that isn't on the list.
"""
import base64
import dataclasses
import datetime
import hashlib
import math
import pathlib
import secrets

KEY_BITS = 2048
PUBLIC_EXPONENT = 65537
VALID_DAYS = 3650
ROOT_NAME = "Local Ad Blocker Root"
LEAF_NAME = "Local Ad Blocker Sites"

_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
_SMALL_PRIMES = [p for p in range(3, 2000) if all(p % d for d in range(2, int(math.sqrt(p)) + 1))]


# --- Keys ---

@dataclasses.dataclass
class RsaKey:
    n: int
    e: int
    d: int
    p: int
    q: int


def _is_probable_prime(candidate, rounds=20):
    if any(candidate % prime == 0 for prime in _SMALL_PRIMES):
        return candidate in _SMALL_PRIMES
    power, odd = 0, candidate - 1
    while odd % 2 == 0:
        power, odd = power + 1, odd // 2
    for _ in range(rounds):
        value = pow(secrets.randbelow(candidate - 3) + 2, odd, candidate)
        if value in (1, candidate - 1):
            continue
        for _ in range(power - 1):
            value = pow(value, 2, candidate)
            if value == candidate - 1:
                break
        else:
            return False
    return True


def _random_prime(bits):
    while True:
        candidate = secrets.randbits(bits) | (0b11 << (bits - 2)) | 1
        if (candidate - 1) % PUBLIC_EXPONENT and _is_probable_prime(candidate):
            return candidate


def generate_key(bits=KEY_BITS):
    while True:
        p, q = _random_prime(bits // 2), _random_prime(bits // 2)
        if p == q:
            continue
        n = p * q
        if n.bit_length() == bits:
            return RsaKey(n, PUBLIC_EXPONENT, pow(PUBLIC_EXPONENT, -1, (p - 1) * (q - 1)), p, q)


# --- The certificate format (DER) ---

def _tlv(tag, content):
    length = len(content)
    if length < 0x80:
        return bytes([tag, length]) + content
    encoded = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(encoded)]) + encoded + content


def _sequence(*parts):
    return _tlv(0x30, b"".join(parts))


def _integer(value):
    return _tlv(0x02, value.to_bytes(value.bit_length() // 8 + 1, "big"))


def _bit_string(data):
    return _tlv(0x03, b"\x00" + data)


def _oid(dotted):
    numbers = [int(part) for part in dotted.split(".")]
    encoded = bytearray([numbers[0] * 40 + numbers[1]])
    for number in numbers[2:]:
        chunk = [number & 0x7F]
        while number := number >> 7:
            chunk.append(0x80 | (number & 0x7F))
        encoded.extend(reversed(chunk))
    return _tlv(0x06, bytes(encoded))


def _time(moment):
    if moment.year < 2050:
        return _tlv(0x17, moment.strftime("%y%m%d%H%M%SZ").encode())
    return _tlv(0x18, moment.strftime("%Y%m%d%H%M%SZ").encode())


def _name(common_name):
    attribute = _sequence(_oid("2.5.4.3"), _tlv(0x0C, common_name.encode()))
    return _sequence(_tlv(0x31, attribute))


def _public_key(key):
    return _sequence(_sequence(_oid("1.2.840.113549.1.1.1"), _tlv(0x05, b"")),
                     _bit_string(_sequence(_integer(key.n), _integer(key.e))))


def _key_id(key):
    return hashlib.sha1(_sequence(_integer(key.n), _integer(key.e))).digest()


def _extension(oid, critical, value):
    flag = _tlv(0x01, b"\xff") if critical else b""
    return _sequence(_oid(oid), flag, _tlv(0x04, value))


def _sign(data, key):
    digest = _SHA256_PREFIX + hashlib.sha256(data).digest()
    size = (key.n.bit_length() + 7) // 8
    padded = b"\x00\x01" + b"\xff" * (size - len(digest) - 3) + b"\x00" + digest
    return pow(int.from_bytes(padded, "big"), key.d, key.n).to_bytes(size, "big")


def _certificate(subject, subject_key, issuer, issuer_key, extensions):
    now = datetime.datetime.now(datetime.timezone.utc)
    algorithm = _sequence(_oid("1.2.840.113549.1.1.11"), _tlv(0x05, b""))
    body = _sequence(
        _tlv(0xA0, _integer(2)),
        _integer(secrets.randbits(120) | (1 << 119)),
        algorithm,
        _name(issuer),
        _sequence(_time(now - datetime.timedelta(days=1)), _time(now + datetime.timedelta(days=VALID_DAYS))),
        _name(subject),
        _public_key(subject_key),
        _tlv(0xA3, _sequence(*extensions)),
    )
    return _sequence(body, algorithm, _bit_string(_sign(body, issuer_key)))


def _dns_names(names):
    return b"".join(_tlv(0x82, name.encode()) for name in names)


def _root_certificate(key, names):
    # A permitted name covers its subdomains too, so wildcards are written without the "*.".
    subtrees = sorted({name.removeprefix("*.") for name in names})
    permitted = _tlv(0xA0, b"".join(_sequence(_tlv(0x82, name.encode())) for name in subtrees))
    return _certificate(ROOT_NAME, key, ROOT_NAME, key, [
        _extension("2.5.29.19", True, _sequence(_tlv(0x01, b"\xff"), _integer(0))),
        _extension("2.5.29.15", True, _tlv(0x03, b"\x01\x06")),
        _extension("2.5.29.30", True, _sequence(permitted)),
        _extension("2.5.29.14", False, _tlv(0x04, _key_id(key))),
    ])


def _site_certificate(key, root_key, names):
    return _certificate(LEAF_NAME, key, ROOT_NAME, root_key, [
        _extension("2.5.29.19", True, _sequence()),
        _extension("2.5.29.15", True, _tlv(0x03, b"\x05\xa0")),
        _extension("2.5.29.37", False, _sequence(_oid("1.3.6.1.5.5.7.3.1"))),
        _extension("2.5.29.17", False, _sequence(_dns_names(names))),
        _extension("2.5.29.14", False, _tlv(0x04, _key_id(key))),
        _extension("2.5.29.35", False, _sequence(_tlv(0x80, _key_id(root_key)))),
    ])


def _private_key_der(key):
    return _sequence(_integer(0), _integer(key.n), _integer(key.e), _integer(key.d), _integer(key.p),
                     _integer(key.q), _integer(key.d % (key.p - 1)), _integer(key.d % (key.q - 1)),
                     _integer(pow(key.q, -1, key.p)))


def _pem(label, der):
    body = base64.b64encode(der).decode()
    lines = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN {label}-----\n{lines}\n-----END {label}-----\n".encode()


# --- Public ---

@dataclasses.dataclass
class CertificatePaths:
    ca_cert: pathlib.Path
    leaf_cert: pathlib.Path
    leaf_key: pathlib.Path


def paths_in(directory):
    directory = pathlib.Path(directory)
    return CertificatePaths(directory / "ca.cer", directory / "leaf.pem", directory / "leaf.key")


def create_certificates(directory, names):
    """Write the root certificate, the site certificate and the site key. The root's key is not kept."""
    root_key = generate_key()
    site_key = generate_key()
    root = _root_certificate(root_key, names)
    site = _site_certificate(site_key, root_key, names)
    del root_key
    paths = paths_in(directory)
    paths.ca_cert.write_bytes(root)
    paths.leaf_cert.write_bytes(_pem("CERTIFICATE", site))
    paths.leaf_key.write_bytes(_pem("RSA PRIVATE KEY", _private_key_der(site_key)))
    return paths
