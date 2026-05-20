"""
Base64 PDF decode diagnostic tool.
Usage: python test_b64_decode.py <base64_file_or_string>
"""
import base64
import sys
import os


def diagnose(s: str) -> bytes | None:
    """Try to decode base64 with various fixes and report what's wrong."""
    stripped = s.strip()
    original_len = len(stripped)

    print(f"=== Base64 Diagnostic ===")
    print(f"Total length:     {original_len}")
    print(f"Length % 4:       {original_len % 4}")
    print(f"Padding needed:   {(4 - original_len % 4) % 4}")
    print()

    # Check character set issues
    standard_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
    actual_chars = set(stripped)
    unknown = actual_chars - standard_chars
    url_safe = {"-", "_"}
    url_safe_found = actual_chars & url_safe

    if unknown:
        # Show context around each unknown char
        print(f"Non-standard chars found: {sorted(unknown)}")
        for ch in sorted(unknown):
            idx = stripped.find(ch)
            while idx != -1:
                ctx_start = max(0, idx - 20)
                ctx_end = min(len(stripped), idx + 20)
                print(f"  char {repr(ch)} at position {idx}: ...{stripped[ctx_start:ctx_end]}...")
                idx = stripped.find(ch, idx + 1)
        print()

    if url_safe_found:
        print(f"URL-safe chars found: {url_safe_found} (will be converted to +/)")
        print()

    # Check for whitespace/newlines (common in copy-pasted base64)
    has_newlines = "\n" in s or "\r" in s
    has_spaces = " " in stripped
    if has_newlines:
        print("Newlines found in input (will be stripped)")
    if has_spaces:
        print("Spaces found in input (will be stripped)")

    # Strategy 1: Add padding only
    padded = stripped
    if len(stripped) % 4 != 0:
        padded += "=" * ((4 - len(stripped) % 4) % 4)
    try:
        result = base64.b64decode(padded)
        print(f"\n  Decode succeeded (Strategy 1: padding only)")
        print(f"  Decoded {len(result)} bytes")
        _check_pdf(result)
        return result
    except Exception as e:
        print(f"  Strategy 1 FAILED (padding only): {e}")

    # Strategy 2: URL-safe chars → standard + padding
    fixed = stripped.replace("-", "+").replace("_", "/")
    if len(fixed) % 4 != 0:
        fixed += "=" * ((4 - len(fixed) % 4) % 4)
    try:
        result = base64.b64decode(fixed)
        print(f"\n  Decode succeeded (Strategy 2: URL-safe + padding)")
        print(f"  Decoded {len(result)} bytes")
        _check_pdf(result)
        return result
    except Exception as e:
        print(f"  Strategy 2 FAILED (URL-safe + padding): {e}")

    # Strategy 3: Try to find and trim garbage prefix/suffix
    print("\n--- Content Sample ---")
    print(f"First 100 chars: {stripped[:100]}")
    print(f"Last 100 chars:  {stripped[-100:]}")
    print()

    # Strategy 4: Validate each character is valid base64 (not padding)
    valid_b64 = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")
    bad_positions = []
    for i, ch in enumerate(stripped.rstrip("=")):
        if ch not in valid_b64:
            bad_positions.append((i, ch))
    if bad_positions:
        print(f"Found {len(bad_positions)} invalid characters (excluding padding):")
        for pos, ch in bad_positions[:20]:
            ctx_start = max(0, pos - 10)
            ctx_end = min(len(stripped), pos + 10)
            print(f"  pos {pos} {repr(ch)} (0x{ord(ch):02x}): ...{stripped[ctx_start:ctx_end]}...")
        if len(bad_positions) > 20:
            print(f"  ... and {len(bad_positions) - 20} more")
    else:
        # If all chars are valid but decode still fails, the base64 content itself is corrupt
        print("All characters are valid base64. The content may be truncated or corrupt.")

    return None


def _check_pdf(data: bytes) -> None:
    """Check if decoded data looks like a PDF."""
    header = data[:10]
    trailer = data[-50:]
    print(f"  First 10 bytes: {header}")
    if header.startswith(b"%PDF"):
        print("  File appears to be a valid PDF")
    else:
        print("  WARNING: File does NOT start with %%PDF magic bytes")
    print(f"  Last 50 bytes:  {trailer}")
    if b"%%EOF" in trailer:
        print("  File ends with %%EOF marker")
    else:
        print("  WARNING: No %%EOF marker found in last 50 bytes")


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_b64_decode.py <base64_string_or_file>")
        print("       python test_b64_decode.py --file <path_to_file>")
        sys.exit(1)

    if sys.argv[1] == "--file" and len(sys.argv) > 2:
        filepath = sys.argv[2]
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            sys.exit(1)
        with open(filepath, "r") as f:
            s = f.read()
        print(f"Read {len(s)} chars from {filepath}\n")
    else:
        s = sys.argv[1]

    result = diagnose(s)

    if result is None:
        print("\n All decode strategies failed.")
        sys.exit(1)
    else:
        # Write decoded output
        out_path = "/tmp/decoded_output.pdf"
        with open(out_path, "wb") as f:
            f.write(result)
        print(f"\n  Decoded PDF written to {out_path}")


if __name__ == "__main__":
    main()