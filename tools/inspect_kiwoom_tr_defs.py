"""Inspect local Kiwoom OpenAPI TR definition files.

The ``C:\\OpenAPI\\data\\*.enc`` files are ZIP containers with CP949-encoded
``.dat`` payloads. This helper prints matching TR definition snippets so new
context mappings can be added without guessing field names.
"""

import argparse
import glob
import os
import zipfile


DEFAULT_DATA_DIR = r"C:\OpenAPI\data"


def main():
    parser = argparse.ArgumentParser(description="Search local Kiwoom TR definition files.")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--patterns",
        default="공매도,잔고,대차,PCR,풋콜,풋,콜,옵션,내재,변동성,선물,투자자,미결제,베이시스",
        help="Comma-separated Korean/English search patterns"
    )
    parser.add_argument("--file", help="Specific enc filename, e.g. opt50023.enc")
    parser.add_argument("--full", action="store_true", help="Print full decoded text for matched files")
    args = parser.parse_args()

    patterns = [item.strip() for item in args.patterns.split(",") if item.strip()]
    paths = [os.path.join(args.data_dir, args.file)] if args.file else glob.glob(os.path.join(args.data_dir, "*.enc"))

    for path in sorted(paths):
        text = read_enc_text(path)
        if text is None:
            continue

        hits = [pattern for pattern in patterns if pattern in text]
        if not hits and not args.file:
            continue

        print("=" * 100)
        print(os.path.basename(path), "hits=" + ",".join(hits))
        print(text if args.full else make_snippet(text, patterns))


def read_enc_text(path):
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if not names:
                return None
            data = archive.read(names[0])
    except Exception:
        return None

    for encoding in ("cp949", "euc-kr", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass

    return data.decode("cp949", "ignore")


def make_snippet(text, patterns, radius=180):
    lowered_text = text
    indexes = [lowered_text.find(pattern) for pattern in patterns if lowered_text.find(pattern) >= 0]
    if not indexes:
        return text[:radius * 2].replace("\r", " ").replace("\n", " ")

    start = max(min(indexes) - radius, 0)
    end = min(max(indexes) + radius, len(text))
    return text[start:end].replace("\r", " ").replace("\n", " ")


if __name__ == "__main__":
    main()
