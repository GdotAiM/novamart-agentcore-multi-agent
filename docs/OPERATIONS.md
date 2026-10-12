# Operations: cost notes and troubleshooting

Back to [README](../README.md).

## Cost notes

These are rough estimates, not billing data. The full verified run (stack, KB creation and sync, about 10 multi-agent executions across the demo, local test, test suites and three invokes, plus deployment) was estimated at **roughly $1–2**. Round 2 (a re-deploy, a local test run, the test suite and five invokes, with a handful of AgentCore Memory events) added an estimated **~$1**. Costs are dominated by Claude Sonnet/Haiku tokens, plus a few cents of Titan embeddings and small DynamoDB, S3, S3 Vectors and CloudWatch charges. At rest, the runtime, memory (events expire after 7 days), Knowledge Bases (on S3 Vectors) and DynamoDB (on-demand) bill almost entirely per use or per GB, so idle cost is small. The main ongoing item is span indexing while X-Ray indexing stays at 100%.

---

## Troubleshooting

| Symptom | What to check |
|---|---|
| `config.py` shows missing tables or buckets | Stack `udacity-agentcore` must be `CREATE_COMPLETE` in `us-east-1`. These values come from CloudFormation exports only. |
| KB IDs show `(not yet created)` | Expected before step 4. Run `scripts/create_knowledge_bases.py` or paste the console IDs into `.env`. |
| A return scenario says "already initiated" | Reseed with `python infrastructure/seed_data.py`. |
| `check_order_status` key-schema error | The Orders key is `customer_id` + `order_id`; pass both. |
| `agentcore: command not found` or old toolkit help | Install Node 20+ and `npm i -g @aws/agentcore@0.30.0`; uninstall `bedrock-agentcore-starter-toolkit`. |
| `agentcore deploy` fails packaging | Needs `uv` on PATH and internet access. See `agentcore/.cli/logs/`. |
| CDK / CloudFormation error on deploy | Check stack `AgentCore-udacity-default`, fix the cause and re-run `deploy`; it is idempotent. |
| No X-Ray traces | Each run prints `X-Ray trace <id> published`. Use "Last 5 minutes" in the console. First-time indexing can take about 10 minutes. |

---

