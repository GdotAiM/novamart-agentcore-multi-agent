# NovaMart: Multi-Agent Customer Support on Amazon Bedrock AgentCore

> **Udacity AWS Agent Engineer project.** This is an enterprise multi-agent architecture built with the [Strands Agents SDK](https://github.com/strands-agents/sdk-python) and deployed to **Amazon Bedrock AgentCore Runtime**. It uses Bedrock Knowledge Bases on S3 Vectors, Bedrock Guardrails, AgentCore Memory, DynamoDB shared workflow state, and CloudWatch + X-Ray observability.

**Status:** deployed end to end on a real AWS account (us-east-1). The course's automated grading suite scored **120 / 120 (100%)**, both before and after the known-issue fixes (AgentCore Memory, multi-turn sessions, delivery-date return windows, reliable refunds, clean replies). See [End-to-end results](#end-to-end-results).

The system automatically routes customer support requests to specialist agents. It retrieves grounded policy knowledge through **parallel multi-agent RAG**, enforces enterprise safety guardrails, and keeps a shared workflow state that every agent can read and update.

<img width="1140" alt="NovaMart architecture overview" src="diagrams/architecture-overview.png" />

---

## Contents

- [Architecture](#architecture)
- [Agents and tools](#agents-and-tools)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Setup and deployment](#setup-and-deployment)
- [End-to-end results](#end-to-end-results)
- [Bugs found and fixed](#bugs-found-and-fixed)
- [Known issues and limitations](#known-issues-and-limitations)
- [Cost notes](#cost-notes)
- [Cleanup](#cleanup)
- [Testing reference](#testing-reference)
- [Troubleshooting](#troubleshooting)
- [Resources](#resources)

---

## Architecture

```
Customer Request
      │
OrchestratorAgent (Claude Haiku 4.5 - routes requests, manages WorkflowState)
      │
   ┌──┼──────────────────────────┬──────────────────┐
   │  │                          │                  │
InventoryAgent    PolicyAgent    RefundAgent    CommunicationAgent
(DynamoDB)     (Multi-Agent RAG)  (DynamoDB)     (synthesizes response)
                     │
         ┌───────────┼───────────┐
    ReturnsPolicyRetriever  ShippingPolicyRetriever  WarrantyPolicyRetriever
    (Bedrock KB)          (Bedrock KB)              (Bedrock KB)
         └───────── run in PARALLEL ───────────┘

Shared State: DynamoDB WorkflowStateTable (with optimistic locking)
```

The orchestrator follows six routing rules:

| Rule | Trigger | Action |
|------|---------|--------|
| 1 | Every request | Call `initialize_session` first |
| 2 | Order status / return / refund | `route_to_inventory_agent`, then `route_to_refund_agent` |
| 3 | Policy questions (windows, rates, terms) | `route_to_policy_agent` |
| 4 | Account questions ("what is my tier?") | `route_to_inventory_agent`, never the PolicyAgent |
| 5 | Maths / calculations | No Inventory, Policy or Refund; go straight to Communication |
| 6 | Every request, last step | `route_to_communication_agent` composes the final reply. The orchestrator never answers directly. |

<img width="1164" alt="Request flow scenarios" src="diagrams/request-flow-scenarios.png" />

### Key features

- **Multi-agent RAG:** the PolicyAgent runs 3 specialised retriever sub-agents in parallel with a `ThreadPoolExecutor` and merges their results.
- **Shared workflow state:** a DynamoDB `WorkflowStateTable` with optimistic locking (version-based conditional writes).
- **Enterprise guardrails:** a Bedrock Guardrail (content filters, PII anonymise/block, denied topics, profanity) attached to every agent's model, including the retriever sub-agents.
- **Observability:** every request becomes one X-Ray trace (Orchestrator → Worker → Knowledge Base). Logs go to CloudWatch, both locally and from the deployed runtime.
- **Conversation memory:** AgentCore Memory (SESSION_SUMMARY). Each turn loads the session's earlier turns and summaries of the customer's past sessions, and saves the new turn. `invoke --session-id` continues a conversation.
- **Knowledge Bases on S3 Vectors:** one vector bucket with one index per Knowledge Base, created by CloudFormation. Embeddings use Titan Text Embeddings v2.

---

## Agents and tools

| Agent | Model | Responsibility | Tools |
|-------|-------|----------------|-------|
| **OrchestratorAgent** | Claude Haiku 4.5 (temp 0.0) | Routes requests; creates and updates WorkflowState | `initialize_session`, `route_to_inventory_agent`, `route_to_policy_agent`, `route_to_refund_agent`, `route_to_communication_agent` |
| **InventoryAgent** | Claude Sonnet 4.5 (temp 0.1) | Gathers order and customer facts from DynamoDB | `check_order_status`, `get_customer_tier`, `list_customer_orders` |
| **PolicyAgent** | Claude Sonnet 4.5 (temp 0.2) | Coordinates parallel retrieval from 3 KBs and synthesises the answer | `search_all_policies` (fans out to 3 retriever sub-agents, temp 0.0) |
| **RefundAgent** | Claude Sonnet 4.5 (temp 0.1) | Return/refund eligibility: 30 days for Standard, 60 days for Premium, counted from delivery, delivered orders only. Initiates the return for explicit, eligible requests. | `get_inventory_context`, `initiate_refund` |
| **CommunicationAgent** | Claude Sonnet 4.5 (temp 0.3) | Drafts the final, empathetic customer-facing reply | `get_full_workflow_context` |

<img width="1165" alt="Agents and tools reference" src="diagrams/agents-and-tools-reference.png" />

---

## Tech stack

| Layer | Technology |
|---|---|
| Agent framework | Strands Agents SDK (Python 3.12) |
| Models | Claude Haiku 4.5 (routing), Claude Sonnet 4.5 (workers) on Amazon Bedrock |
| Hosting | Amazon Bedrock AgentCore Runtime (CodeZip, arm64, PUBLIC / HTTP), deployed with the **AgentCore CLI 0.30.0** (`@aws/agentcore`, CDK under the hood) |
| Memory | AgentCore Memory (SESSION_SUMMARY strategy, 7-day event expiry) |
| RAG | Bedrock Knowledge Bases, Titan Text Embeddings v2 (1024-d), Amazon S3 Vectors |
| Safety | Amazon Bedrock Guardrails (Standard tier, cross-region profile) |
| Data | Amazon DynamoDB (orders, customers, workflow state), Amazon S3 (policy documents) |
| Infrastructure | AWS CloudFormation (`infrastructure/starter_stack.yaml`) |
| Observability | CloudWatch Logs, AWS X-Ray, CloudWatch Transaction Search |

---

## Repository layout

```
.
├── config.py                      # Central configuration (CloudFormation exports + .env)
├── requirements.txt
├── .env.example                   # Template - copy to .env (never commit .env)
├── agentcore/                     # AgentCore CLI project used by `agentcore deploy`
│   ├── agentcore.json             # Runtime definition (as deployed: role + env vars)
│   ├── aws-targets.json           # Deployment target (account + region)
│   └── cdk/                       # CDK app the CLI deploys with
├── src/
│   ├── agent_orchestrator.py      # The 5-agent system, guardrail, deploy, memory, observability, serve entry point
│   ├── agent_observability.py     # X-Ray tracing + CloudWatch logging layer
│   ├── agentcore_cli.py           # AgentCore CLI wrapper (stage code, deploy, status)
│   ├── bedrock_kb_retrieval.py    # KB retrieval helper
│   ├── agent_utils.py             # Terminal trace UI
│   └── demo.py                    # One-shot demo with a visual trace
├── infrastructure/
│   ├── starter_stack.yaml         # DynamoDB, S3, S3 Vectors, IAM role, log group
│   ├── seed_data.py               # Seeds customers, orders and policy documents
│   └── cleanup.py                 # Deletes everything the project created
├── scripts/
│   └── create_knowledge_bases.py  # API alternative to the console KB wizard (create + sync + fill .env)
├── tests/
│   ├── test_agent.py              # Automated grading suite (120 points, unchanged)
│   └── test_known_issues.py       # Offline pytest suite for the known-issue fixes (moto)
├── diagrams/                      # Architecture diagrams
└── docs/
    ├── FIXES.md                   # Bugs found in the starter and how they were fixed
    ├── fixes.diff                 # Full patch against the original starter
    └── screenshots/               # Terminal captures of the real end-to-end run
```

---

## Prerequisites

- **Python 3.12**, which matches the deployed runtime.
- An **AWS account** in `us-east-1` with access to Bedrock (Claude Haiku 4.5, Claude Sonnet 4.5, Titan Text Embeddings v2), Bedrock AgentCore, DynamoDB, S3, S3 Vectors, CloudFormation, IAM (`CAPABILITY_NAMED_IAM`), CloudWatch and X-Ray. The AgentCore CLI deploys through AWS CDK, so the account needs a CDK bootstrap (`CDKToolkit`), which the first deploy creates.
- **Node.js 20+** with the AgentCore CLI, and [**uv**](https://docs.astral.sh/uv/getting-started/installation/), which the CLI uses to download arm64 wheels:

  ```bash
  npm install -g @aws/agentcore@0.30.0
  agentcore --version
  ```

  > The CLI replaces the older Python `bedrock-agentcore-starter-toolkit`. If you have the old one installed, uninstall it (`pip uninstall bedrock-agentcore-starter-toolkit`). CLI 0.30.0 warns that Node 22+ will be required for updates published after January 2027.

---

## Setup and deployment

This is the exact command flow used for the verified run.

### 1. Install dependencies and configure the environment

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
```

### 2. Deploy the foundation stack

```bash
aws cloudformation deploy \
  --stack-name udacity-agentcore \
  --template-file infrastructure/starter_stack.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

This creates three DynamoDB tables, the policy-documents bucket, an S3 Vectors bucket with three indexes (`returns-`, `shipping-` and `warranty-policy-index`), the AgentCore execution role and the log group.

### 3. Check the configuration and seed the data

```bash
python config.py                     # prints every resolved resource name
python infrastructure/seed_data.py   # 4 customers, 11 orders, 6 policy documents
```

### 4. Create and sync the three Knowledge Bases

**Option A: API (used in the verified run)**

```bash
python scripts/create_knowledge_bases.py
```

This creates `novamart-returns-policy-kb`, `novamart-shipping-policy-kb` and `novamart-warranty-policy-kb`. Each is a self-managed KB using Titan v2 embeddings (1024, FLOAT32) on the stack's S3 Vectors bucket and index, with one S3 data source per policy prefix. The script syncs each KB, waits until ingestion is `COMPLETE` and writes the IDs into `.env`. It uses the stack's execution role as the KB service role; that role trusts `bedrock.amazonaws.com` and already has S3 read, `s3vectors:*` and `bedrock:InvokeModel`.

**Option B: console.** Go to Bedrock → Knowledge Bases → Create (self-managed, existing S3 Vectors store). Use the following settings, then click **Sync** on each data source and paste the IDs into `.env` as `RETURNS_KB_ID`, `SHIPPING_KB_ID` and `WARRANTY_KB_ID`.

| Setting | Returns KB | Shipping KB | Warranty KB |
|---|---|---|---|
| S3 data bucket | *Policy Bucket* from `python config.py` | same | same |
| S3 prefix | `policies/returns/` | `policies/shipping/` | `policies/warranty/` |
| Embedding model | `amazon.titan-embed-text-v2:0` | same | same |
| Vector bucket | *Vector Bucket* from `python config.py` | same | same |
| Vector index | `returns-policy-index` | `shipping-policy-index` | `warranty-policy-index` |

Do **not** use *Quick create a new vector store*.

**Console view of the three Knowledge Bases.** Each uses Titan Text Embeddings v2 on the stack's S3 Vectors store, with its data source on the matching `policies/<name>/` prefix and a completed sync. The console leaves the *S3 vector index* field blank, so the index names (`returns-policy-index`, `shipping-policy-index`, `warranty-policy-index`) are confirmed from the Bedrock API in [docs/knowledge-bases.json](docs/knowledge-bases.json).

![Bedrock console: the three NovaMart Knowledge Bases](docs/screenshots/kb-console/kb-list.png)

### 5. Test locally

```bash
python tests/test_agent.py task2
python tests/test_agent.py task5
python src/demo.py
python infrastructure/seed_data.py         # reseed (see note below)
python src/agent_orchestrator.py test      # 3 live scenarios, X-Ray traces published
```

> **Reseed note:** a successful return changes the order's status to `Return Initiated`, after which it is no longer eligible (by design, see [fix 4](docs/FIXES.md)). Returns are now actually created by the return scenario, so re-run `seed_data.py` before each full run of the scenarios or the test suite.

### 6. Deploy to AgentCore Runtime

```bash
python src/agent_orchestrator.py deploy
```

This runs a 6-step pipeline:

1. Build the graph.
2. Create the Guardrail and publish a numbered version.
3. Stage `build/runtime/` and run `agentcore deploy -y` (CDK stack `AgentCore-udacity-default`).
4. Create AgentCore Memory.
5. Configure observability (CloudWatch logs, X-Ray Transaction Search, runtime environment variables).
6. Deploy the optional gateway, which is skipped unless Lambda tool functions are configured.

Copy the printed values into `.env`:

```
AGENTCORE_RUNTIME_ARN=<printed arn>
GUARDRAIL_ID=<printed id>
GUARDRAIL_VERSION=<printed version>
AGENTCORE_MEMORY_ID=<printed memory id>   # enables memory for local runs too
```

The deployed runtime receives `AGENTCORE_MEMORY_ID` automatically.

### 7. Verify

```bash
python infrastructure/seed_data.py
python tests/test_agent.py all
python src/agent_orchestrator.py invoke "I want to return my wireless headphones from order ORD-27176" CUST-001
python src/agent_orchestrator.py invoke "What is the return policy for premium customers?" CUST-002
python src/agent_orchestrator.py invoke 'How much would 5 items at $29.99 be with a 10% discount?' CUST-003
agentcore status

# multi-turn: reuse the session id printed by the first call
python src/agent_orchestrator.py invoke "I want to return my phone case from order ORD-30001 - it's the wrong colour" CUST-004 --session-id demo1
python src/agent_orchestrator.py invoke "What was my return reference again?" CUST-004 --session-id demo1

# offline tests for the known-issue fixes (no AWS needed)
pip install pytest moto && pytest -q tests/test_known_issues.py
```

The X-Ray Service Map for the course submission is in CloudWatch → X-Ray traces → Service map (see [Observability (X-Ray)](#observability-x-ray)). After the first live run, allow about 10 minutes for spans to be indexed.

---

## End-to-end results

Everything below comes from real runs on 26 Sep 2026 in `us-east-1`. The screenshots are terminal captures of those runs' logs, with credentials scrubbed. The account ID and resource IDs are visible; they are not secrets.

There were two rounds:

- **Round 1:** the first deployment, which produced the original "Known issues".
- **Round 2:** the known-issue fixes, followed by a re-deploy and re-verification. Unless marked otherwise, the results below are from round 2.

### Deployed resources

| Resource | Value |
|---|---|
| Foundation stack | `udacity-agentcore` (CREATE_COMPLETE) |
| Knowledge Bases | returns `PD8S9AR9AT`, shipping `JH2SOUPQEE`, warranty `8G7AOXWUTD`. Each sync: 2 documents scanned, 2 indexed, 0 failed. |
| Guardrail | `i8p6i1mpnel9`, version `1` |
| AgentCore Runtime | `udacity_agentcore_runtime-ETnTL1HEGn`: READY (PUBLIC / HTTP), updated in place by the round-2 deploy |
| AgentCore Memory | `udacity_agentcore_memory-Q347dYFGUi`: ACTIVE, now **used** by the agents (`AGENTCORE_MEMORY_ID` in the runtime environment) |
| CLI / CDK stack | `AgentCore-udacity-default` |
| Observability | Log group `/aws/bedrock/agentcore/udacity-agentcore`; X-Ray → CloudWatch Logs (Transaction Search ACTIVE, 100% indexing) |

### Grading suite: 120 / 120 (after the fixes)

| Task | Area | Score |
|---|---|---|
| Task 2 | Multi-agent orchestration | **40 / 40** |
| Task 3 | AgentCore Runtime + Guardrails | **20 / 20** |
| Task 4 | Memory | **15 / 15** |
| Task 5 | Bedrock Knowledge Bases | **25 / 25** |
| Task 6 | Observability | **20 / 20** |
| **Total** | `python tests/test_agent.py all` | **120 / 120 (100%)** |

No checks failed, in either round. The offline tests for the fixes, `tests/test_known_issues.py`, pass 17/17.

![Final score 120/120](docs/screenshots/11-test-all-p2.png)
*`tests/test_agent.py all` after the round-2 re-deploy: **Score: 120/120 pts (100%)**.*

**Re-run with the starter's files restored (26 Sep 2026, 21:09 SAST).** After `starter_stack.yaml`, `seed_data.py` and `demo.py` were reverted to the exact starter versions and the data was reseeded with the original `seed_data.py`, the full suite was run again against the live deployment: **120/120, no failures**. Terminal screenshots are below, and the full text output is in [docs/test-all-output.txt](docs/test-all-output.txt).

![Terminal: 120/120 after restoring the starter files](docs/screenshots/24-test-all-terminal.png)
*Live terminal: Task 5 and Task 6 checks and **Score: 120/120 pts (100%)**.* Earlier tasks: [25-test-all-terminal-top.png](docs/screenshots/25-test-all-terminal-top.png).

### Deployed runtime: the three demo scenarios (`invoke`)

| Scenario | Outcome (round 2) |
|---|---|
| **Return:** "I want to return my wireless headphones from order ORD-27176" (CUST-001, Premium) | **The return was created.** Alice received a confirmation with return reference `RET-27176-36065`, the $149.99 refund, packing and label instructions, and the note that her order was delivered on 18 Sep 2026, within the Premium 60-day window counted *from delivery*. DynamoDB confirms `status = Return Initiated`, `return_reason = "Customer requested return (no reason given)"`. In round 1 the model asked for a reason and created nothing. |
| **Policy:** "What is the return policy for premium customers?" (CUST-002) | A grounded answer from the three Knowledge Bases: a 60-day Premium window versus 30 days Standard, the qualification criteria ($500+ per year or 20+ orders), the 6-step return process and Premium benefits (free expedited shipping, 3-year electronics warranty, 4-hour priority support). |
| **Maths:** "How much would 5 items at $29.99 be with a 10% discount?" (CUST-003) | $149.95 minus $14.995 gives **$134.96**, routed straight to Communication. **The reply now starts with "Hello!"**, with no leaked reasoning. In round 1 it began "I can see that this is a pricing calculation question…". |

| Return | Policy | Maths |
|---|---|---|
| ![Invoke - return](docs/screenshots/12-invoke-return.png) | ![Invoke - policy](docs/screenshots/13-invoke-policy.png) | ![Invoke - maths](docs/screenshots/14-invoke-math.png) |

![DynamoDB after the return invoke](docs/screenshots/16-return-dynamodb.png)
*The order record after the return invoke: `Return Initiated`, with return reference `RET-27176-36065`. (This capture predates restoring `seed_data.py` to the starter version, so it still shows a `delivered_date` field.)*

### Multi-turn session with AgentCore Memory

Two `invoke` calls sharing `--session-id demo172232` (CUST-004):

1. **Turn 1:** "I want to return my phone case from order ORD-30001 - it's the wrong colour". The return was created with reference `RET-30001-36178`, and the customer's own reason (`Wrong colour`) was stored.
2. **Turn 2:** "Sorry, what was my return reference again, and which item was it for?" This message contains **no order ID**. The answer was: "Your return reference is **RET-30001-36178**, and it's for the **Phone Case Slim** from order ORD-30001."

AgentCore Memory holds both turns (USER + ASSISTANT events for actor `CUST-004`, session `demo172232`). The WorkflowState row shows `turn=2`, with 966 characters of memory context loaded for the second turn.

| Turn 1 | Turn 2 |
|---|---|
| ![Session turn 1](docs/screenshots/17-session-turn1.png) | ![Session turn 2](docs/screenshots/18-session-turn2.png) |

![Memory events](docs/screenshots/19-memory-events.png)
*`list_events` on the AgentCore Memory, plus the order and WorkflowState records for the session.*

### Observability (X-Ray)

Screenshots taken live in the CloudWatch X-Ray console (us-east-1, 1-hour range) after the round-2 runs:

![X-Ray trace map](docs/screenshots/22-xray-service-map.png)
*Trace Map: **Client** → **NovaMart-Orchestrator**, fanning out to **InventoryAgent**, **RefundAgent**, **PolicyAgent** and **CommunicationAgent**, and to the three Knowledge Base nodes **KnowledgeBase:returns**, **KnowledgeBase:shipping** and **KnowledgeBase:warranty**.*

![X-Ray traces](docs/screenshots/23-xray-traces.png)
*Traces list for `NovaMart-Orchestrator`: **8 traces, all OK**, average response time **27.73 s** (17:13–17:23 SAST). These are the round-2 local `test` scenarios and deployed `invoke` calls.*

### Local runs

- **Round 1:**
  - `demo.py` routed Orchestrator → Inventory → Refund → Communication in **25.7 s**.
  - `agent_orchestrator.py test` routed all 3 scenarios as specified: Inventory → Refund for the return, 3 parallel KB retrievers for the policy question, and straight to Communication for the maths.
  - The Task 5 retrievers answered in parallel in 7.1 s.
- **Round 2:** `agent_orchestrator.py test` routed all 3 scenarios correctly again. The return called `initiate_refund` (`RET-27176-35607`), and the maths reply was clean.
- **Offline:** the mocked harness (moto plus a scripted model) ran every mode (`test`, `demo`, `chat`, `serve`, `deploy`, `invoke`) end to end, and pytest passed 17/17.

### Deployment

![Deploy pipeline](docs/screenshots/10-deploy.png)
*Round-2 `deploy`: the runtime was updated in place, and Step 4 now adds `AGENTCORE_MEMORY_ID` to the runtime environment.*

![agentcore status](docs/screenshots/15-agentcore-status.png)
*`agentcore status`: runtime deployed and READY.*

![Knowledge Base sync](docs/screenshots/04-kb-sync.png)
*Round 1: the three Knowledge Bases were created through the API and synced (ingestion COMPLETE, 0 failures).*

<details>
<summary><b>Full screenshot gallery (all captures)</b></summary>

| # | Step | Screenshot |
|---|---|---|
| 01 | CloudFormation stack deploy + outputs (round 1) | [01-stack.png](docs/screenshots/01-stack.png) |
| 02 | `python config.py` (round 1) | [02-config.png](docs/screenshots/02-config.png) |
| 03 | `seed_data.py` (round 1) | [03-seed.png](docs/screenshots/03-seed.png) |
| 04 | Knowledge Bases created + synced (round 1) | [04-kb-sync.png](docs/screenshots/04-kb-sync.png) |
| 05 | `test_agent.py task2`: 40/40 (round 1) | [05-test-task2.png](docs/screenshots/05-test-task2.png) |
| 06 | `test_agent.py task5`: 25/25 (round 1) | [p1](docs/screenshots/06-test-task5-p1.png) · [p2](docs/screenshots/06-test-task5-p2.png) |
| 07 | `demo.py` (round 1) | [p1](docs/screenshots/07-demo-p1.png) · [p2](docs/screenshots/07-demo-p2.png) |
| 08 | Reseed (round 1) | [08-reseed.png](docs/screenshots/08-reseed.png) |
| 09 | `agent_orchestrator.py test` (round 1) | [p1](docs/screenshots/09-local-test-p1.png) · [p2](docs/screenshots/09-local-test-p2.png) · [p3](docs/screenshots/09-local-test-p3.png) · [p4](docs/screenshots/09-local-test-p4.png) · [p5](docs/screenshots/09-local-test-p5.png) · [p6](docs/screenshots/09-local-test-p6.png) |
| 10 | `agent_orchestrator.py deploy` (round 2) | [10-deploy.png](docs/screenshots/10-deploy.png) |
| 11 | `test_agent.py all`: 120/120 (round 2) | [p1](docs/screenshots/11-test-all-p1.png) · [p2](docs/screenshots/11-test-all-p2.png) |
| 12 | `invoke`: return scenario (round 2) | [12-invoke-return.png](docs/screenshots/12-invoke-return.png) |
| 13 | `invoke`: policy scenario (round 2) | [13-invoke-policy.png](docs/screenshots/13-invoke-policy.png) |
| 14 | `invoke`: maths scenario (round 2) | [14-invoke-math.png](docs/screenshots/14-invoke-math.png) |
| 15 | `agentcore status` (round 2) | [15-agentcore-status.png](docs/screenshots/15-agentcore-status.png) |
| 16 | DynamoDB order after the return invoke | [16-return-dynamodb.png](docs/screenshots/16-return-dynamodb.png) |
| 17 | Same-session invoke: turn 1 | [17-session-turn1.png](docs/screenshots/17-session-turn1.png) |
| 18 | Same-session invoke: turn 2 | [18-session-turn2.png](docs/screenshots/18-session-turn2.png) |
| 19 | AgentCore Memory events + state | [19-memory-events.png](docs/screenshots/19-memory-events.png) |
| 20 | `pytest tests/test_known_issues.py`: 17 passed | [20-unit-tests.png](docs/screenshots/20-unit-tests.png) |
| 21 | X-Ray `Default` indexing rule (100%) | [21-xray-indexing.png](docs/screenshots/21-xray-indexing.png) |
| 22 | X-Ray console: Trace/Service Map (1 h) | [22-xray-service-map.png](docs/screenshots/22-xray-service-map.png) |
| 23 | X-Ray console: NovaMart-Orchestrator traces (8, all OK) | [23-xray-traces.png](docs/screenshots/23-xray-traces.png) |
| 24 | Terminal: `tests/test_agent.py all` 120/120 with starter files restored | [24-test-all-terminal.png](docs/screenshots/24-test-all-terminal.png) |
| 25 | Terminal: earlier tasks of the same run | [25-test-all-terminal-top.png](docs/screenshots/25-test-all-terminal-top.png) |
| KB | Bedrock console: the three Knowledge Bases (list and details) | [kb-list](docs/screenshots/kb-console/kb-list.png) · [returns](docs/screenshots/kb-console/kb-returns-1.png) ([2](docs/screenshots/kb-console/kb-returns-2.png)) · [shipping](docs/screenshots/kb-console/kb-shipping-1.png) ([2](docs/screenshots/kb-console/kb-shipping-2.png)) · [warranty](docs/screenshots/kb-console/kb-warranty-1.png) ([2](docs/screenshots/kb-console/kb-warranty-2.png)) |

![01 stack](docs/screenshots/01-stack.png)
![20 unit tests](docs/screenshots/20-unit-tests.png)
![11 test all p1](docs/screenshots/11-test-all-p1.png)

</details>

---

## Bugs found and fixed

The starter was audited before deployment, and the live run revealed a few more issues. **17 fixes** are described in **[docs/FIXES.md](docs/FIXES.md)**. Three of them (1, 2 and 11) changed starter files on the course's "never modify" list and have since been **reverted**, so 14 remain in place. The round-1 patch is in [docs/fixes.diff](docs/fixes.diff).

**Round 1 (before the first deployment):**

- **Refund safety:** only `delivered` orders are eligible, which prevents double refunds.
- **Session isolation:** agents' conversation histories are cleared per request.
- **Concurrency:** the `serve` entry point serialises concurrent invocations.
- **Guardrail:** attached to the retriever sub-agents too, and always a numbered version.
- Explicit Bedrock region and `Decimal` → `int`.

**Round 2 (the "Known issues" from the first live run):**

- **AgentCore Memory is wired in.** Each turn loads the session's earlier turns and summaries of the customer's past sessions, then saves the new turn. It is skipped cleanly when `AGENTCORE_MEMORY_ID` isn't set.
- **Multi-turn sessions.** `invoke --session-id` gives a stable runtime session, and WorkflowState starts a fresh *turn* on the same session.
- **Delivery-date return windows.** Eligibility counts from `delivered_date` when an order has one, then from `estimated_delivery` once that date has passed, then from `order_date`. The starter's seed data has no `delivered_date`, so seeded orders use `estimated_delivery`; every seeded verdict is unchanged.
- **Reliable refunds.** A prompt change plus a deterministic backstop mean an eligible, explicit return request always creates the return.
- **Clean replies.** A strict output format and a sanitiser remove any agent narration before the reply reaches the customer.

> **Note:** every file on the course's "never modify" list is identical to the Udacity starter, including `infrastructure/starter_stack.yaml`, `infrastructure/seed_data.py`, `src/demo.py`, `config.py` and `tests/test_agent.py`. All fixes live in `src/agent_orchestrator.py` (the student file). `tests/test_known_issues.py` is a new, additional file.

---

## Known issues and limitations

- **X-Ray indexing stays at 100% (by design of the grading suite).** Task 6 (`test_6_2_xray_tracing_enabled`, 10 points) requires the account-level X-Ray indexing rule `Default` to be exactly 100%. The pre-written `agent_observability.py` sets it during deploy, so it was left at 100% for grading. It applies to the **whole account** and adds span-indexing cost. After grading, lower it to the AWS default:

  ```bash
  aws xray update-indexing-rule --name Default \
    --rule '{"Probabilistic":{"DesiredSamplingPercentage":1}}' --region us-east-1
  ```

  Re-running `deploy` sets it back to 100%.
- **Memory summaries are asynchronous.** SESSION_SUMMARY records for past sessions are generated by AgentCore in the background, so a brand-new session only sees the summaries that already exist. Turns within the current session come from raw events and are available immediately.
- **The refund backstop is heuristic.** "Explicit return intent" is detected with patterns such as "I want to return…", "please start a return…" and "refund my…". Phrasing it doesn't recognise falls back to the LLM's own decision. Questions like "Can I return…?" deliberately only report eligibility.
- **The reply sanitiser is heuristic too.** It removes narration it can recognise; the prompt's output-format rules are the primary control.
- **Seeded delivery dates are estimates.** The starter's seed data only has `estimated_delivery` (order date + 5 days), which is used as the delivery basis. Real integrations should write the carrier's delivery date into `delivered_date`.
- **Node.js version.** AgentCore CLI 0.30.0 runs on Node 20 but warns that Node 22+ will be required for updates after January 2027.

---

## Cost notes

These are rough estimates, not billing data. The full verified run (stack, KB creation and sync, about 10 multi-agent executions across the demo, local test, test suites and three invokes, plus deployment) was estimated at **roughly $1–2**. Round 2 (a re-deploy, a local test run, the test suite and five invokes, with a handful of AgentCore Memory events) added an estimated **~$1**. Costs are dominated by Claude Sonnet/Haiku tokens, plus a few cents of Titan embeddings and small DynamoDB, S3, S3 Vectors and CloudWatch charges. At rest, the runtime, memory (events expire after 7 days), Knowledge Bases (on S3 Vectors) and DynamoDB (on-demand) bill almost entirely per use or per GB, so idle cost is small. The main ongoing item is span indexing while X-Ray indexing stays at 100%.

---

## Cleanup

When you're finished (after taking the submission screenshots):

```bash
python infrastructure/cleanup.py          # dry run - lists what would be deleted
python infrastructure/cleanup.py --yes    # deletes it (run twice; KB/AgentCore deletions are async)
```

This deletes, in dependency order:

1. The three Knowledge Bases and their data sources.
2. The AgentCore CLI stack `AgentCore-udacity-default` (runtime) and the Memory.
3. The Guardrail.
4. The policy bucket contents.
5. The `udacity-agentcore` stack (tables, buckets, vector indexes, role, log group).
6. The runtime log groups.

> ⚠️ **Don't add `--disable-transaction-search` if anything else in the account uses AgentCore Observability or CloudWatch Transaction Search.** It turns Transaction Search off for the whole account, not just this project. The `CDKToolkit` bootstrap stack is shared and is left in place.

---

## Testing reference

```bash
python tests/test_agent.py task2   # Multi-agent orchestration (40)
python tests/test_agent.py task3   # AgentCore Runtime + Guardrails (20)
python tests/test_agent.py task4   # Memory (15)
python tests/test_agent.py task5   # Knowledge Bases (25)
python tests/test_agent.py task6   # Observability (20)
python tests/test_agent.py all     # Full suite (120)
pytest -q tests/test_known_issues.py  # Offline tests for the known-issue fixes

python src/agent_orchestrator.py test    # 3 live scenarios, locally
python src/agent_orchestrator.py chat    # interactive session with a colour-coded agent trace
python src/agent_orchestrator.py invoke "<question>" CUST-00X [--session-id ID]   # call the deployed runtime

agentcore invoke '{"prompt": "I want to return my order ORD-27176", "customer_id": "CUST-001"}'
agentcore status
agentcore logs
```

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

## Resources

- [Strands Agents SDK](https://github.com/strands-agents/sdk-python)
- [Amazon Bedrock AgentCore developer guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/)
- [AgentCore CLI (`@aws/agentcore`)](https://github.com/aws/agentcore-cli)
- [Bedrock Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
- [Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-create.html) · [safeguard tiers](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-tiers.html)
- [DynamoDB conditional writes / optimistic locking](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html)

---

*Based on the Udacity AWS Agent Engineer course starter, "Enterprise Multi-Agent Architecture with Amazon Bedrock AgentCore". Course materials remain subject to Udacity's terms.*
