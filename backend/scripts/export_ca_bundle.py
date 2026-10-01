"""Export the Windows-trusted TLS CAs to a PEM file for ``COPILOT_CA_BUNDLE``.

Run on the IIS server as an account whose certificate store trusts the corporate CA,
grant the app pool identity read access to the output, then set COPILOT_CA_BUNDLE to it.

    python backend\\scripts\\export_ca_bundle.py C:\\inetpub\\cotrace\\corp-ca.pem --check
"""
from __future__ import annotations

import argparse
import ssl
import sys
from pathlib import Path

_SERVER_AUTH_OID = "1.3.6.1.5.5.7.3.1"
_DEFAULT_CHECK_URL = "https://copilot-api.intel-foundry.ghe.com/models"
_DEFAULT_PROXY = "http://proxy-us.intel.com:912"


def collect_pem_certs() -> list[str]:
    seen: set[bytes] = set()
    pems: list[str] = []
    for store in ("ROOT", "CA"):
        for der, encoding, trust in ssl.enum_certificates(store):
            if encoding != "x509_asn" or der in seen:
                continue
            if trust is not True and _SERVER_AUTH_OID not in trust:
                continue
            seen.add(der)
            pems.append(ssl.DER_cert_to_PEM_cert(der))
    return pems


def check_tls(bundle: Path, url: str, proxy: str) -> int:
    """Unauthenticated request: any HTTP status proves the TLS chain verified."""
    import httpx  # noqa: PLC0415

    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(bundle))
    try:
        with httpx.Client(proxy=proxy or None, verify=context, trust_env=False, timeout=20) as client:
            status = client.get(url, follow_redirects=False).status_code
    except httpx.HTTPError as exc:
        print(f"TLS check FAILED for {url}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"TLS check OK for {url} (HTTP {status}).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path, help="PEM file to write")
    parser.add_argument("--check", action="store_true", help="verify TLS to the Copilot API with the bundle")
    parser.add_argument("--check-url", default=_DEFAULT_CHECK_URL)
    parser.add_argument("--proxy", default=_DEFAULT_PROXY, help="proxy for --check ('' for none)")
    args = parser.parse_args()

    if not hasattr(ssl, "enum_certificates"):
        print("This script reads the Windows certificate store and must run on Windows.", file=sys.stderr)
        return 2
    pems = collect_pem_certs()
    if not pems:
        print("No server-auth CA certificates found.", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(pems), encoding="ascii")
    print(f"Wrote {len(pems)} CA certificates to {args.output}.")
    return check_tls(args.output, args.check_url, args.proxy) if args.check else 0


if __name__ == "__main__":
    sys.exit(main())
