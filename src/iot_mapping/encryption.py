"""
Simple XOR obfuscation for map data.

NOT cryptographically secure — this just prevents casual viewing of
device locations in the raw HTML source. The same password is used
client-side (in map_app.js) to decrypt and display the data.
"""

import base64


def obfuscate_data(data_string: str, password: str) -> str:
    """XOR each byte of data with cycling password bytes, then base64-encode."""
    if not password:
        return data_string

    key_bytes = password.encode("utf-8")
    data_bytes = data_string.encode("utf-8")

    obfuscated = bytearray()
    for i, byte in enumerate(data_bytes):
        # Cycle through password: byte 0 uses key[0], byte 1 uses key[1], etc.
        obfuscated.append(byte ^ key_bytes[i % len(key_bytes)])

    return base64.b64encode(obfuscated).decode("utf-8")
