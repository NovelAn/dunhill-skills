# QuickBI Failure Propagation Design

## Goal

Prevent the daily workflow from reporting success when the required
`BI_dtc_t01_trade_order_line` source was not captured or imported.

## Design

The QuickBI crawler will retry each failed report within the same authenticated
browser context. After the final attempt, it will return a failed result and the
QuickBI worker process will exit non-zero. The parent pipeline will propagate a
critical QuickBI worker failure instead of continuing to report overall success.

Step 1's Playwright MCP Extension routing will include both DTC order and DTC
successful-refund sources. It will read the page result count and create a full
offline export only when the result exceeds the 50-row preview limit. Results at
or below 50 rows remain assigned to Step 2's headless crawler.

Step 2 will also perform an unconditional final check for today's required
QuickBI files. If any are missing, Step 2 returns failure and prints an explicit
action message. The orchestrator can then classify the failure into
`needs_action`, and no success notification will be sent.

## Constraints

- Do not run the full ingestion workflow while implementing or testing.
- Do not write to the database.
- Preserve macOS exclusion of Steps 3-5.
- Do not modify credentials, cookies, or local configuration.

## Testing

- Unit-test retry success after an initial empty result.
- Unit-test failure after exhausting retries.
- Unit-test that Step 2 rejects a nominally successful subprocess when a
  required QuickBI file is still missing.
- Run existing daily status and LaunchAgent management tests.
