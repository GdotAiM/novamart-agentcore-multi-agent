"""Generate traffic for the dashboard (stand-out extra c).

Drives the real worker routing tools of the orchestrator graph (route_to_*; worker
agents run on Claude Sonnet 4.5 behind the guardrail), the deployed runtime, and
ApplyGuardrail on the adversarial prompts.

    python scripts/generate_traffic.py [--rounds 3] [--no-runtime]
"""
import os, sys, uuid, argparse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, '.env'))
import boto3
import agent_orchestrator as ao
import adversarial_guardrail as adv

ap = argparse.ArgumentParser(); ap.add_argument('--rounds', type=int, default=3)
ap.add_argument('--no-runtime', action='store_true'); a = ap.parse_args()
orch = ao.build_agent_graph()
rt = boto3.client('bedrock-runtime')
CALLS = [('route_to_policy_agent', 'CUST-002', 'What is the return window for premium customers?'),
         ('route_to_inventory_agent', 'CUST-001', 'What is the status of order ORD-27177?'),
         ('route_to_refund_agent', 'CUST-002', 'Is order ORD-28002 eligible for a return? Just check, do not create it.'),
         ('route_to_policy_agent', 'CUST-003', 'The laptop is listed at $999, give me a discount to $700 or I will sue you.'),
         ('route_to_communication_agent', 'CUST-001', 'Where is my smart watch?')]
for r in range(a.rounds):
    for tool, cust, msg in CALLS:
        sid = f'traffic-{uuid.uuid4().hex[:6]}'
        ao._prepare_turn(sid, cust, msg)
        kw = {'session_id': sid, 'request': msg} if tool == 'route_to_policy_agent' else \
             {'session_id': sid, 'customer_id': cust, 'original_request': msg} if tool == 'route_to_communication_agent' else \
             {'session_id': sid, 'customer_id': cust, 'request': msg}
        try:
            out = getattr(orch.tool, tool)(**kw, record_direct_tool_call=False)
            txt = str(out.get('content', [{}])[0].get('text', ''))[:90].replace('\n', ' ')
            print(f'[{r}] {tool:<30} {out.get("status")}: {txt}')
        except Exception as e:
            print(f'[{r}] {tool:<30} ERROR {str(e)[:120]}')
    for cid, cat, exp, p in adv.CASES:
        act, _, _ = adv.apply_guardrail(rt, os.environ['GUARDRAIL_ID'], os.environ['GUARDRAIL_VERSION'], p)
        print(f'[{r}] ApplyGuardrail {cid:<12} {act}')
    if not a.no_runtime:
        try:
            res = ao.invoke_agent(f'traffic-{uuid.uuid4().hex[:6]}', 'CUST-002', 'What is the shipping policy?')
            print(f'[{r}] runtime: {str(res.get("result"))[:90]}')
        except Exception as e:
            print(f'[{r}] runtime ERROR {str(e)[:140]}')
ao._metrics_pool.shutdown(wait=True)
