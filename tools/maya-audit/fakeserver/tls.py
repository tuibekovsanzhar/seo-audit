"""Generate throwaway certificates for local HTTPS test servers (needs the dev dependency `cryptography`)."""

from __future__ import annotations

import datetime as dt
import ipaddress
import os
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


@dataclass
class CertFiles:
    cert: str
    key: str


def _key():
    return ec.generate_private_key(ec.SECP256R1())


def _write(directory: str, name: str, cert: x509.Certificate, key) -> CertFiles:
    cert_path = os.path.join(directory, f"{name}.pem")
    key_path = os.path.join(directory, f"{name}.key")
    with open(cert_path, "wb") as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as fh:
        fh.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption()))
    return CertFiles(cert_path, key_path)


class TestCA:
    """A local certificate authority whose PEM file serves as the crawler's trust store in tests."""

    __test__ = False  # not a pytest test class

    def __init__(self, directory: str, name: str = "Maya Test CA") -> None:
        self.directory = directory
        self.key = _key()
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        now = dt.datetime.now(dt.timezone.utc)
        self.cert = (
            x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject).public_key(self.key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(self.key.public_key()), critical=False)
            .sign(self.key, hashes.SHA256())
        )
        self.files = _write(directory, name.replace(" ", "_").lower(), self.cert, self.key)

    def issue(self, name: str, hostnames=("localhost",), days_valid: float = 365, expired: bool = False) -> CertFiles:
        key = _key()
        now = dt.datetime.now(dt.timezone.utc)
        not_after = now - dt.timedelta(days=1) if expired else now + dt.timedelta(days=days_valid)
        not_before = min(now - dt.timedelta(days=2), not_after - dt.timedelta(days=1))
        alt_names = []
        for host in hostnames:
            try:
                alt_names.append(x509.IPAddress(ipaddress.ip_address(host)))
            except ValueError:
                alt_names.append(x509.DNSName(host))
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostnames[0])]))
            .issuer_name(self.cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(not_before).not_valid_after(not_after)
            .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(self.key.public_key()), critical=False)
            .sign(self.key, hashes.SHA256())
        )
        return _write(self.directory, name, cert, key)
