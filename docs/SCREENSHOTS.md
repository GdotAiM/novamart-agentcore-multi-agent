# Screenshot gallery

All captures from the live runs (us-east-1, 26 Sep 2026). Credentials scrubbed; account and resource IDs are not secrets. Back to [README](../README.md).

| # | Step | Screenshot |
|---|---|---|
| 01 | CloudFormation stack deploy + outputs (round 1) | [01-stack.png](screenshots/01-stack.png) |
| 02 | `python config.py` (round 1) | [02-config.png](screenshots/02-config.png) |
| 03 | `seed_data.py` (round 1) | [03-seed.png](screenshots/03-seed.png) |
| 04 | Knowledge Bases created + synced (round 1) | [04-kb-sync.png](screenshots/04-kb-sync.png) |
| 05 | `test_agent.py task2`: 40/40 (round 1) | [05-test-task2.png](screenshots/05-test-task2.png) |
| 06 | `test_agent.py task5`: 25/25 (round 1) | [p1](screenshots/06-test-task5-p1.png) · [p2](screenshots/06-test-task5-p2.png) |
| 07 | `demo.py` (round 1) | [p1](screenshots/07-demo-p1.png) · [p2](screenshots/07-demo-p2.png) |
| 08 | Reseed (round 1) | [08-reseed.png](screenshots/08-reseed.png) |
| 09 | `agent_orchestrator.py test` (round 1) | [p1](screenshots/09-local-test-p1.png) · [p2](screenshots/09-local-test-p2.png) · [p3](screenshots/09-local-test-p3.png) · [p4](screenshots/09-local-test-p4.png) · [p5](screenshots/09-local-test-p5.png) · [p6](screenshots/09-local-test-p6.png) |
| 10 | `agent_orchestrator.py deploy` (round 2) | [10-deploy.png](screenshots/10-deploy.png) |
| 11 | `test_agent.py all`: 120/120 (round 2) | [p1](screenshots/11-test-all-p1.png) · [p2](screenshots/11-test-all-p2.png) |
| 12 | `invoke`: return scenario (round 2) | [12-invoke-return.png](screenshots/12-invoke-return.png) |
| 13 | `invoke`: policy scenario (round 2) | [13-invoke-policy.png](screenshots/13-invoke-policy.png) |
| 14 | `invoke`: maths scenario (round 2) | [14-invoke-math.png](screenshots/14-invoke-math.png) |
| 15 | `agentcore status` (round 2) | [15-agentcore-status.png](screenshots/15-agentcore-status.png) |
| 16 | DynamoDB order after the return invoke | [16-return-dynamodb.png](screenshots/16-return-dynamodb.png) |
| 17 | Same-session invoke: turn 1 | [17-session-turn1.png](screenshots/17-session-turn1.png) |
| 18 | Same-session invoke: turn 2 | [18-session-turn2.png](screenshots/18-session-turn2.png) |
| 19 | AgentCore Memory events + state | [19-memory-events.png](screenshots/19-memory-events.png) |
| 20 | `pytest tests/test_known_issues.py`: 17 passed | [20-unit-tests.png](screenshots/20-unit-tests.png) |
| 21 | X-Ray `Default` indexing rule (100%) | [21-xray-indexing.png](screenshots/21-xray-indexing.png) |
| 22 | X-Ray console: Trace/Service Map (1 h) | [22-xray-service-map.png](screenshots/22-xray-service-map.png) |
| 23 | X-Ray console: NovaMart-Orchestrator traces (8, all OK) | [23-xray-traces.png](screenshots/23-xray-traces.png) |
| 24 | Terminal: `tests/test_agent.py all` 120/120 with starter files restored | [24-test-all-terminal.png](screenshots/24-test-all-terminal.png) |
| 25 | Terminal: earlier tasks of the same run | [25-test-all-terminal-top.png](screenshots/25-test-all-terminal-top.png) |
| KB | Bedrock console: the three Knowledge Bases (list and details) | [kb-list](screenshots/kb-console/kb-list.png) · [returns](screenshots/kb-console/kb-returns-1.png) ([2](screenshots/kb-console/kb-returns-2.png)) · [shipping](screenshots/kb-console/kb-shipping-1.png) ([2](screenshots/kb-console/kb-shipping-2.png)) · [warranty](screenshots/kb-console/kb-warranty-1.png) ([2](screenshots/kb-console/kb-warranty-2.png)) |

![01 stack](screenshots/01-stack.png)
![20 unit tests](screenshots/20-unit-tests.png)
![11 test all p1](screenshots/11-test-all-p1.png)

