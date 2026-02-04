#!/usr/bin/env python3
"""
Tool skeleton for workspace/tools.

Usage:
  python workspace/tools/<name>.py --arg value
"""

import argparse
import json
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Tool skeleton")
    parser.add_argument("--example", required=True)
    args = parser.parse_args()

    # Example: read API key from .env / environment
    api_key = os.environ.get("EXAMPLE_API_KEY")
    if not api_key:
        print(json.dumps({"success": False, "error": "Missing EXAMPLE_API_KEY"}))
        sys.exit(1)

    # TODO: implement tool logic
    result = {"echo": args.example}

    print(json.dumps({"success": True, "data": result}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)
