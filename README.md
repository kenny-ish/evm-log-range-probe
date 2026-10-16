# EVM Log Range Probe

EVM Log Range Probe measures the largest block interval that each EVM JSON-RPC provider accepts for the same `eth_getLogs` filter. It is useful when an indexer needs to choose a safe log-query window or explain why providers fail at different ranges.

## Example 1

This is a real run against Ethereum mainnet on 2026-10-10 UTC. The filter targets the WETH contract and the ERC-20 `Transfer` event over 64 blocks.

```text
$ python evm_log_range_probe.py \
    --rpc https://ethereum-rpc.publicnode.com \
    --rpc https://eth.drpc.org \
    --from-block 0x18f3602 \
    --to-block 0x18f3641 \
    --address 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
    --topic0 0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef
{
  "from": 26162690,
  "to": 26162753,
  "providers": [
    {
      "chain_id": 1,
      "end_hash": "0x3a54208d3789f4c7ed4829159f53293f3643170297158a07488127e8ad840b9a",
      "status": "input_cap_accepted",
      "accepted_span": 64,
      "rejected_span": null,
      "logs": 2910,
      "probes": [
        [
          1,
          "ok",
          2
        ],
        [
          2,
          "ok",
          62
        ],
        [
          4,
          "ok",
          140
        ],
        [
          8,
          "ok",
          302
        ],
        [
          16,
          "ok",
          665
        ],
        [
          32,
          "ok",
          1387
        ],
        [
          64,
          "ok",
          2910
        ]
      ]
    },
    {
      "chain_id": 1,
      "end_hash": "0x3a54208d3789f4c7ed4829159f53293f3643170297158a07488127e8ad840b9a",
      "status": "input_cap_accepted",
      "accepted_span": 64,
      "rejected_span": null,
      "logs": 2910,
      "probes": [
        [
          1,
          "ok",
          2
        ],
        [
          2,
          "ok",
          62
        ],
        [
          4,
          "ok",
          140
        ],
        [
          8,
          "ok",
          302
        ],
        [
          16,
          "ok",
          665
        ],
        [
          32,
          "ok",
          1387
        ],
        [
          64,
          "ok",
          2910
        ]
      ]
    }
  ],
  "comparison": "comparable"
}
```

## Example 2

This is a second real run against Optimism mainnet on 2026-10-10 UTC. It uses the canonical Optimism WETH contract and the same `Transfer` topic over 32 blocks.

```text
$ python evm_log_range_probe.py \
    --rpc https://mainnet.optimism.io \
    --rpc https://optimism.publicnode.com \
    --from-block 0x96b3f31 \
    --to-block 0x96b3f50 \
    --address 0x4200000000000000000000000000000000000006 \
    --topic0 0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef
{
  "from": 158023473,
  "to": 158023504,
  "providers": [
    {
      "chain_id": 10,
      "end_hash": "0x673cf37e8841140b49dd62115029418204d9d06cd05b890eec54adc49485e790",
      "status": "input_cap_accepted",
      "accepted_span": 32,
      "rejected_span": null,
      "logs": 846,
      "probes": [
        [
          1,
          "ok",
          12
        ],
        [
          2,
          "ok",
          25
        ],
        [
          4,
          "ok",
          58
        ],
        [
          8,
          "ok",
          124
        ],
        [
          16,
          "ok",
          312
        ],
        [
          32,
          "ok",
          846
        ]
      ]
    },
    {
      "chain_id": 10,
      "end_hash": "0x673cf37e8841140b49dd62115029418204d9d06cd05b890eec54adc49485e790",
      "status": "input_cap_accepted",
      "accepted_span": 32,
      "rejected_span": null,
      "logs": 846,
      "probes": [
        [
          1,
          "ok",
          12
        ],
        [
          2,
          "ok",
          25
        ],
        [
          4,
          "ok",
          58
        ],
        [
          8,
          "ok",
          124
        ],
        [
          16,
          "ok",
          312
        ],
        [
          32,
          "ok",
          846
        ]
      ]
    }
  ],
  "comparison": "comparable"
}
```

The output is a snapshot from those runs. Range limits can depend on the event filter and response size, so an accepted span is not a universal limit for every filter. A successful query with zero matching logs still counts as an accepted range.

## Usage

```text
python evm_log_range_probe.py --rpc URL --rpc URL --from-block BLOCK --to-block BLOCK --address ADDRESS --topic0 TOPIC
```

Repeat `--rpc` for each provider. `--from-block` and `--to-block` accept decimal numbers or hexadecimal quantities and the inclusive range must contain at most 65,536 blocks. `--address` is the contract whose logs should be queried. `--topic0` is the 32-byte event signature hash. Use `--json` for compact JSON. The tool uses only the supplied JSON-RPC URLs and does not call an explorer or an indexing service.

## How it works

For each provider, the tool anchors the end block, then sends `eth_getLogs` for suffix ranges of 1, 2, 4, and larger block spans. If a provider explicitly rejects a range, the tool binary-searches between the last accepted span and the first rejected span. Rate limits, timeouts, malformed responses, and unstable end blocks are reported as inconclusive rather than being mistaken for a range limit. Returned logs are checked for the requested address, topic, block range, duplicate positions, and removed entries.

## Tests

```text
python -m unittest -v
```
