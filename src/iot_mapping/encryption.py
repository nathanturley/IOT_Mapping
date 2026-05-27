import base64


def obfuscate_data(data_string: str, password: str) -> str:
    """XOR-encrypt data with a cycling password key and base64-encode the result."""
    if not password:
        return data_string

    key_bytes = password.encode("utf-8")
    data_bytes = data_string.encode("utf-8")

    obfuscated = bytearray()
    for i, byte in enumerate(data_bytes):
        obfuscated.append(byte ^ key_bytes[i % len(key_bytes)])

    return base64.b64encode(obfuscated).decode("utf-8")
