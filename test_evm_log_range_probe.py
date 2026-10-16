import copy
import io
import unittest
from unittest.mock import patch

import evm_log_range_probe as m


TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
# Reduced real log fields from the Ethereum and Optimism live cases.
LOGS = [
    {"address": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "topics": [TOPIC], "blockNumber": "0x18f3641", "blockHash": "0x3a54208d3789f4c7ed4829159f53293f3643170297158a07488127e8ad840b9a", "transactionHash": "0xbcd1a3c8c2c2b8b00c74f206c10a6295d85f40eceda6eeca8554e5c8fa9a416b", "logIndex": "0x3f", "removed": False},
    {"address": "0x4200000000000000000000000000000000000006", "topics": [TOPIC], "blockNumber": "0x96b3f50", "blockHash": "0x673cf37e8841140b49dd62115029418204d9d06cd05b890eec54adc49485e790", "transactionHash": "0x64329166d1be0dfe5800e02c2ebd4654fbb3b3a4aabb6cbb7c6a45c8eeb527c5", "logIndex": "0x10", "removed": False},
]
# Counts from actual eth_getLogs responses, not fabricated log arrays.
COUNTS = [
    {1: 2, 2: 62, 4: 140, 8: 302, 16: 665, 32: 1387, 64: 2910, 128: 6800, 256: 11378},
    {1: 12, 2: 25, 4: 58, 8: 124, 16: 312, 32: 846},
]


class ProbeTests(unittest.TestCase):
    def test_live_count_replays(self):
        for counts in COUNTS:
            report = m.find_boundary(counts.__getitem__, max(counts))
            self.assertEqual(report["accepted_span"], max(counts))
            self.assertEqual(report["logs"], counts[max(counts)])
            self.assertEqual(report["status"], "input_cap_accepted")

    def test_real_logs(self):
        for log in LOGS:
            number = int(log["blockNumber"], 16)
            self.assertEqual(m.log_count([log], number, number, log["address"], TOPIC), 1)

    def test_duplicates_and_bad_filter(self):
        log = LOGS[0]
        number = int(log["blockNumber"], 16)
        for logs in ([log, log], [dict(log, removed=True)], [dict(log, topics=[])], [dict(log, blockNumber="0x1")]):
            with self.assertRaises(ValueError):
                m.log_count(logs, number, number, log["address"], TOPIC)

    def test_binary_search(self):
        def fetch(span):
            if span > 5:
                raise m.RpcError("block range exceeds limit", -32005)
            return span * 2
        report = m.find_boundary(fetch, 32)
        self.assertEqual((report["accepted_span"], report["rejected_span"]), (5, 6))
        self.assertEqual(report["status"], "observed_boundary")

    def test_transient_is_not_limit(self):
        for error in (m.RpcError("rate limit", -32005, 429), m.RpcError("timeout"), m.RpcError("method not found", -32601), m.RpcError("bad request", status=400)):
            def fetch(span):
                if span > 1:
                    raise error
                return 0
            report = m.find_boundary(fetch, 8)
            self.assertEqual(report["status"], "inconclusive")
            self.assertIsNone(report["rejected_span"])

    def test_unstable_boundary(self):
        calls = {}
        def fetch(span):
            calls[span] = calls.get(span, 0) + 1
            if span > 1 and calls[span] == 1:
                raise m.RpcError("block range too wide")
            return 0
        self.assertEqual(m.find_boundary(fetch, 2)["status"], "unstable")

    def test_single_block_rejected(self):
        def fetch(span):
            raise m.RpcError("too many results")
        self.assertEqual(m.find_boundary(fetch, 1)["status"], "single_block_rejected")

    def test_validation(self):
        for start, end in ((-1, 2), (2, 1), (0, 65536)):
            with self.assertRaises(ValueError):
                m.probe(["a", "b"], start, end, LOGS[0]["address"], TOPIC)
        with self.assertRaises(ValueError):
            m.probe(["a", "a"], 1, 2, LOGS[0]["address"], TOPIC)

    def test_http_user_agent(self):
        body = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"result":"0x1"}')
        with patch.object(m.urllib.request, "urlopen", return_value=body) as opened:
            self.assertEqual(m.rpc_call("https://example.invalid", "eth_chainId", []), "0x1")
        self.assertEqual(opened.call_args.args[0].get_header("User-agent"), "evm-log-range-probe/0.2")

    def test_http_error_body(self):
        body = b'{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"eth_getLogs is limited to 100 blocks"}}'
        error = m.urllib.error.HTTPError("https://example.invalid", 400, "bad", {}, io.BytesIO(body))
        with patch.object(m.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(m.RpcError) as caught:
                m.rpc_call("https://example.invalid", "eth_getLogs", [])
        self.assertTrue(m.range_rejection(caught.exception))

    def test_reorg(self):
        calls = 0
        def call(url, method, params):
            nonlocal calls
            if method == "eth_chainId":
                return "0x1"
            if method == "eth_getLogs":
                return []
            calls += 1
            return {"number": "0x1", "hash": "0x" + ("11" if calls == 1 else "22") * 32}
        report = m.probe_provider("a", 1, 1, LOGS[0]["address"], TOPIC, call)
        self.assertEqual(report["status"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
