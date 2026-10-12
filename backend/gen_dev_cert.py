"""
gen_dev_cert.py — Generate a self-signed TLS certificate for local HTTPS.

WHY THIS IS NEEDED:
    Meta's Facebook JS SDK enforces HTTPS for FB.login() since 2018:
    https://developers.facebook.com/blog/post/2018/06/08/enforce-https-facebook-login/

    Running the backend on http://127.0.0.1:8000 means FB.login() will be
    silently rejected and the Embedded Signup popup will not open.

USAGE:
    python gen_dev_cert.py

OUTPUT:
    certs/dev-cert.pem  — self-signed certificate
    certs/dev-key.pem   — private key

THEN RUN UVICORN WITH:
    python -m uvicorn main:app --host 127.0.0.1 --port 8000 \
        --ssl-certfile certs/dev-cert.pem \
        --ssl-keyfile  certs/dev-key.pem

BROWSER:
    Open https://127.0.0.1:8000
    Accept the self-signed cert warning once.

NOTE: The cert is for local development only. Never use in production.
"""

import datetime
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


CERTS_DIR = Path(__file__).resolve().parent / "certs"
CERT_FILE = CERTS_DIR / "dev-cert.pem"
KEY_FILE  = CERTS_DIR / "dev-key.pem"


def generate():
    CERTS_DIR.mkdir(exist_ok=True)

    # --- Generate RSA private key ---
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # --- Build certificate ---
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Dev"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Localhost"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AXIOM Dev"),
        x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=825))
        # Subject Alternative Names required by modern browsers
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    # --- Write key ---
    KEY_FILE.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    # --- Write cert ---
    CERT_FILE.write_bytes(
        cert.public_bytes(serialization.Encoding.PEM)
    )

    print(f"[gen_dev_cert] Certificate: {CERT_FILE}")
    print(f"[gen_dev_cert] Private key: {KEY_FILE}")
    print()
    print("Run the server with HTTPS:")
    print()
    print(
        "  python -m uvicorn main:app "
        "--host 127.0.0.1 --port 8000 "
        "--ssl-certfile certs/dev-cert.pem "
        "--ssl-keyfile certs/dev-key.pem"
    )
    print()
    print("Then open: https://127.0.0.1:8000")
    print("Accept the browser self-signed cert warning once.")


if __name__ == "__main__":
    generate()
