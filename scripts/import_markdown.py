#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One-time import: each Markdown note in a folder becomes one observation.

Dry run unless --write is given. Notes that look like they hold secrets are
skipped and listed by name only. With --write, imported notes are recorded in
--log, so a stopped import can be rerun without creating duplicates.
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.request

SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY|\bgh[pousr]_[A-Za-z0-9]{20}|\bgithub_pat_\w{20}"
    r"|\bsk-[A-Za-z0-9_-]{20}|\bAKIA[A-Z0-9]{16}\b|\bxox[abprs]-[A-Za-z0-9-]{10}"
    r"|\bAGE-SECRET-KEY-|\btskey-\w+-\w+|\beyJ[\w-]{10,}\.[\w-]{10,}\."
    r"|(?i:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[\"']?[A-Za-z0-9+/_-]{16,}"
)


def note_body(text):
    """Put name and description first, so the embedding always covers them."""
    match = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not match:
        return text.strip()
    front, rest = match.groups()

    def field(key):
        found = re.search(rf"^\s*{key}:\s*(.+)$", front, re.M)
        return found.group(1).strip().strip("\"'") if found else ""

    head = ": ".join(part for part in (field("name"), field("description")) if part)
    kind = field("type")
    return "\n\n".join(
        part for part in (head, f"Type: {kind}" if kind else "", rest.strip()) if part
    )


class Client:
    def __init__(self, url, account, profile, agent):
        label = json.dumps(
            {
                "version": 1,
                "account_id": account,
                "agent_profile_id": profile,
                "agent_name": agent,
            }
        ).encode()
        self.url = url
        self.next_id = 0
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-PocketCoder-Memory-Context": base64.urlsafe_b64encode(label)
            .rstrip(b"=")
            .decode(),
        }

    def request(self, method, params):
        self.next_id += 1
        body = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
        request = urllib.request.Request(
            self.url, json.dumps(body).encode(), self.headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            reply = json.load(response)
        if "error" in reply:
            raise RuntimeError(reply["error"])
        return reply["result"]

    def call(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(result)
        return result["structuredContent"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--account", required=True)
    parser.add_argument("--profile", default="markdown-import")
    parser.add_argument("--agent", default="markdown-import")
    parser.add_argument("--exclude", action="append", default=["MEMORY.md"])
    parser.add_argument("--log", help="required with --write")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write and not args.log:
        parser.error("--write needs --log")

    done = {}
    if args.log and os.path.exists(args.log):
        with open(args.log, encoding="utf-8") as log:
            done = dict(json.loads(line) for line in log)

    notes, skipped = [], []
    for name in sorted(os.listdir(args.folder)):
        path = os.path.join(args.folder, name)
        if not name.endswith(".md") or name in args.exclude or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as file:
            text = file.read()
        if SECRET.search(text):
            skipped.append(name)
        elif note_body(text) and name not in done:
            notes.append((name, note_body(text)))

    print(f"to import: {len(notes)}, already imported: {len(done)}, skipped: {len(skipped)}")
    for name in skipped:
        print(f"possible secret, skipped: {name}")
    if not args.write:
        print("dry run: nothing written")
        return 0

    client = Client(args.url, args.account, args.profile, args.agent)
    with open(args.log, "a", encoding="utf-8") as log:
        for name, body in notes:
            record = client.call("memory_create_observation", {"body": body})
            log.write(json.dumps([name, record["id"]]) + "\n")
            log.flush()
    print(f"imported: {len(notes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
