#!/usr/bin/env python3
"""Compare an embedded Authenticode SpcIndirectDataContent digest to PE bytes.

Requires pefile and Python hashlib. This validates only PE image-digest agreement;
it does not verify CMS/RSA signature validity, certificate trust, timestamps or revocation.
The input is read-only.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import pefile


def read_tlv(data: bytes, pos: int):
    if pos >= len(data):
        raise ValueError("truncated ASN.1 tag")
    tag = data[pos]
    pos += 1
    if pos >= len(data):
        raise ValueError("truncated ASN.1 length")
    first = data[pos]
    pos += 1
    if first < 0x80:
        length = first
    else:
        n = first & 0x7f
        if not n or n > 4 or pos + n > len(data):
            raise ValueError("unsupported/truncated ASN.1 length")
        length = int.from_bytes(data[pos:pos+n], "big")
        pos += n
    end = pos + length
    if end > len(data):
        raise ValueError("ASN.1 object exceeds containing buffer")
    return tag, data[pos:end], end


def children(data: bytes):
    result = []
    pos = 0
    while pos < len(data):
        tag, content, end = read_tlv(data, pos)
        result.append((tag, content))
        pos = end
    if pos != len(data):
        raise ValueError("ASN.1 child list was not consumed exactly")
    return result


def spc_digest(der: bytes):
    tag, root_content, end = read_tlv(der, 0)
    if tag != 0x30 or end != len(der):
        raise ValueError("certificate payload is not one DER SEQUENCE")
    ci = children(root_content)
    if len(ci) != 2 or ci[0][0] != 0x06 or ci[1][0] != 0xa0:
        raise ValueError("not a PKCS#7 ContentInfo SignedData envelope")
    explicit = children(ci[1][1])
    if len(explicit) != 1 or explicit[0][0] != 0x30:
        raise ValueError("malformed SignedData envelope")
    signed_data = children(explicit[0][1])
    # SignedData: version, digestAlgorithms, encapContentInfo, optional certs/CRLs, signerInfos.
    encap = next((x for x in signed_data if x[0] == 0x30 and b"\x06\x0a+\x06\x01\x04\x01\x82\x37\x02\x01\x04" in x[1]), None)
    if encap is None:
        raise ValueError("Microsoft SpcIndirectDataContent not found")
    encap_parts = children(encap[1])
    if len(encap_parts) < 2 or encap_parts[1][0] != 0xa0:
        raise ValueError("malformed EncapsulatedContentInfo")
    indirect_explicit = children(encap_parts[1][1])
    if len(indirect_explicit) != 1 or indirect_explicit[0][0] != 0x30:
        raise ValueError("malformed SpcIndirectDataContent")
    indirect = children(indirect_explicit[0][1])
    if len(indirect) < 2 or indirect[1][0] != 0x30:
        raise ValueError("missing DigestInfo")
    digest_info = children(indirect[1][1])
    if len(digest_info) != 2 or digest_info[1][0] != 0x04:
        raise ValueError("malformed DigestInfo")
    algo = children(digest_info[0][1])
    if not algo or algo[0][0] != 0x06:
        raise ValueError("missing digest algorithm OID")
    # The PE in this analysis uses SHA-1; reject other algorithms rather than guess.
    if algo[0][1] != bytes.fromhex("2b0e03021a"):
        raise ValueError(f"unsupported embedded digest algorithm OID bytes: {algo[0][1].hex()}")
    return digest_info[1][1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("executable", type=Path)
    args = ap.parse_args()
    path = args.executable
    blob = path.read_bytes()
    pe = pefile.PE(str(path), fast_load=False)
    opt_off = pe.DOS_HEADER.e_lfanew + 24
    checksum_off = opt_off + 64
    security_dir_entry_off = opt_off + (96 if pe.OPTIONAL_HEADER.Magic == 0x10b else 112) + 8*4
    cert_off = pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].VirtualAddress
    cert_size = pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size
    if not cert_off or cert_off + cert_size > len(blob):
        raise SystemExit("PE has no in-bounds Certificate Table")

    expected = None
    pos = cert_off
    end = cert_off + cert_size
    while pos + 8 <= end:
        length, revision, cert_type = struct.unpack_from("<IHH", blob, pos)
        if length < 8 or pos + length > end:
            raise SystemExit("invalid WIN_CERTIFICATE record")
        if cert_type == 2:
            expected = spc_digest(blob[pos+8:pos+length])
            break
        pos += (length + 7) & ~7
    if expected is None:
        raise SystemExit("no PKCS#7 SignedData record found")

    excluded = sorted([(checksum_off, 4), (security_dir_entry_off, 8), (cert_off, cert_size)])
    h = hashlib.sha1()
    cursor = 0
    for start, length in excluded:
        if start < cursor:
            raise SystemExit("overlapping Authenticode excluded ranges")
        h.update(blob[cursor:start])
        cursor = start + length
    h.update(blob[cursor:])
    actual = h.digest()
    result = {
        "file": str(path), "size": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
        "certificate_table_file_offset": f"0x{cert_off:08x}",
        "certificate_table_size": f"0x{cert_size:08x}",
        "embedded_digest_algorithm": "SHA-1",
        "embedded_digest": expected.hex(),
        "computed_authenticode_digest": actual.hex(),
        "digest_match": actual == expected,
        "signature_and_trust_chain_verified": False,
        "excluded_ranges": [{"file_offset": f"0x{start:08x}", "size": length} for start, length in excluded],
    }
    print(json.dumps(result, indent=2))
    pe.close()


if __name__ == "__main__":
    main()
