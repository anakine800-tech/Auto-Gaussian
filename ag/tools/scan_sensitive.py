"""Scan changed Git blobs without printing potentially sensitive values."""

import argparse
import re
import subprocess


def git(*args):
    return subprocess.check_output(["git", *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--base")
    source.add_argument("--staged", action="store_true")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    if args.staged:
        revisions = ["--cached"]
        prefix = ":"
    else:
        base, head = [git("rev-parse", "--verify", "--end-of-options",
                          f"{ref}^{{commit}}").decode().strip()
                      for ref in (args.base, args.head)]
        revisions = [base, head]
        prefix = f"{head}:"
    paths = git("diff", "--name-only", "-z", "--no-renames",
                "--diff-filter=ACMRT", *revisions, "--").split(b"\0")
    octet = rb"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
    patterns = {
        "private key": rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----",
        "IPv4 address": rb"(?<![\w.])" + octet + rb"(?:\." + octet + rb"){3}(?![\w.])",
        "user directory": rb"/(?:home|Users)/[A-Za-z0-9_.-]+",
    }
    failed = False
    for raw_path in filter(None, paths):
        path = raw_path.decode("utf-8", errors="surrogateescape")
        data = git("show", f"{prefix}{path}")
        for label, pattern in patterns.items():
            if re.search(pattern, data):
                print(f"Sensitive information ({label}): {path}")
                failed = True
    if not failed:
        print("Sensitive information scan passed.")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
