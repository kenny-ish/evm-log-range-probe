#!/usr/bin/env python3
"""Find an observed eth_getLogs acceptance boundary, not a universal limit."""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request


class RpcError(Exception):
    def __init__(self, message, code=None, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


def quantity(value):
    if not isinstance(value, str) or not re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", value):
        raise ValueError("invalid RPC quantity")
    return int(value, 16)


def block_number(value):
    if not re.fullmatch(r"(?:[0-9]+|0x[0-9a-fA-F]+)", str(value)):
        raise ValueError("block must be nonnegative")
    return int(str(value), 16 if str(value).startswith("0x") else 10)


def hex_data(value, size):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{%d}" % (size * 2), value):
        raise ValueError("invalid hex value")
    return value.lower()


def rpc_call(url, method, params):
    request = urllib.request.Request(
        url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        {"Content-Type": "application/json", "User-Agent": "evm-log-range-probe/0.2"},
    )
    status = None
    try:
        try:
            response = urllib.request.urlopen(request, timeout=20)
        except urllib.error.HTTPError as exc:
            status = exc.code
            response = exc
        with response:
            raw = response.read(16777217)
        if len(raw) > 16777216:
            raise RpcError("response exceeds 16 MiB")
        body = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise RpcError(type(exc).__name__, status=status) from exc
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or type(body.get("id")) is not int or body["id"] != 1:
        raise RpcError("invalid JSON-RPC envelope", status=status)
    error = body.get("error")
    if isinstance(error, dict):
        raise RpcError(str(error.get("message", "RPC error")), error.get("code"), status)
    if status is not None or "result" not in body:
        raise RpcError("HTTP failure or missing result", status=status)
    return body["result"]


def range_rejection(exc):
    text = str(exc).lower()
    if exc.status in (401, 403, 408, 429) or (exc.status and exc.status >= 500):
        return False
    if any(word in text for word in ("rate limit", "per second", "quota", "timeout", "archive")):
        return False
    subjects = ("block range", "block span", "blocks range", "too many results", "too many logs", "response size", "result limit")
    if "eth_getlogs" in text and "blocks" in text and any(w in text for w in ("limit", "maximum", "exceed", "unsupported", "not supported")):
        return True
    if "block" in text and any(w in text for w in ("limit", "maximum", "exceed", "unsupported", "not supported", "too wide", "too large")):
        return True
    return any(s in text for s in subjects) and any(w in text for w in ("limit", "maximum", "exceed", "too", "large", "wide"))


def log_count(logs, start, end, address, topic):
    if not isinstance(logs, list):
        raise ValueError("logs result is not an array")
    seen = set()
    for log in logs:
        if not isinstance(log, dict):
            raise ValueError("invalid log")
        number = quantity(log.get("blockNumber"))
        topics = log.get("topics")
        if not start <= number <= end or hex_data(log.get("address"), 20) != address:
            raise ValueError("log outside filter")
        if not isinstance(topics, list) or not topics or hex_data(topics[0], 32) != topic or log.get("removed") is not False:
            raise ValueError("wrong topic or removed log")
        key = (hex_data(log.get("blockHash"), 32), quantity(log.get("logIndex")))
        hex_data(log.get("transactionHash"), 32)
        if key in seen:
            raise ValueError("duplicate log")
        seen.add(key)
    return len(logs)


def find_boundary(fetch, available):
    if not 1 <= available <= 65536:
        raise ValueError("span must be between 1 and 65536 blocks")
    probes = []
    best, failed, count = 0, None, None

    def attempt(span):
        try:
            value = fetch(span)
            probes.append([span, "ok", value])
            return value
        except RpcError as exc:
            probes.append([span, "error", str(exc)])
            if not range_rejection(exc):
                raise
            return None

    def result(status):
        return {"status": status, "accepted_span": best or None, "rejected_span": failed, "logs": count, "probes": probes}

    try:
        span = 1
        while True:
            value = attempt(span)
            if value is None:
                failed = span
                break
            best, count = span, value
            if span == available:
                return result("input_cap_accepted")
            span = min(span * 2, available)
        while failed - best > 1:
            middle = (best + failed) // 2
            value = attempt(middle)
            if value is None:
                failed = middle
            else:
                best, count = middle, value
        if not best:
            return result("single_block_rejected")
        if attempt(best) != count or attempt(failed) is not None:
            return result("unstable")
        return result("observed_boundary")
    except (RpcError, ValueError, TypeError) as exc:
        report = result("inconclusive")
        report["error"] = str(exc)
        return report


def probe_provider(url, start, end, address, topic, call=rpc_call):
    report = {}
    try:
        report["chain_id"] = quantity(call(url, "eth_chainId", []))
        def anchor():
            block = call(url, "eth_getBlockByNumber", [hex(end), False])
            if not isinstance(block, dict) or quantity(block.get("number")) != end:
                raise ValueError("wrong or missing end block")
            return hex_data(block.get("hash"), 32)
        report["end_hash"] = anchor()
        def fetch(span):
            first = end - span + 1
            query = {"fromBlock": hex(first), "toBlock": hex(end), "address": address, "topics": [topic]}
            return log_count(call(url, "eth_getLogs", [query]), first, end, address, topic)
        report.update(find_boundary(fetch, end - start + 1))
        if anchor() != report["end_hash"]:
            raise ValueError("end block changed during probes")
    except (RpcError, ValueError, TypeError) as exc:
        report.update(status="inconclusive", error=str(exc))
    return report


def probe(urls, start, end, address, topic, call=rpc_call):
    start, end = block_number(start), block_number(end)
    if not 1 <= end - start + 1 <= 65536:
        raise ValueError("inclusive range must contain 1 to 65536 blocks")
    if len(urls) < 2 or len(set(urls)) != len(urls):
        raise ValueError("supply at least two distinct RPC URLs")
    address, topic = hex_data(address, 20), hex_data(topic, 32)
    providers = [probe_provider(u, start, end, address, topic, call) for u in urls]
    complete = all(p["status"] in ("input_cap_accepted", "observed_boundary") for p in providers)
    status = "inconclusive"
    if complete:
        identity = {(p["chain_id"], p["end_hash"]) for p in providers}
        status = "comparable" if len(identity) == 1 else "different_chain_or_block"
    return {"from": start, "to": end, "providers": providers, "comparison": status}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc", action="append", required=True)
    parser.add_argument("--from-block", required=True)
    parser.add_argument("--to-block", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--topic0", required=True)
    parser.add_argument("--json", action="store_true", help="compact JSON")
    args = parser.parse_args(argv)
    try:
        report = probe(args.rpc, args.from_block, args.to_block, args.address, args.topic0)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=None if args.json else 2))
    return 0 if report["comparison"] == "comparable" else 2


if __name__ == "__main__":
    sys.exit(main())
