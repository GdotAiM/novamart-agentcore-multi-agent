"""
Offline unit tests for the fixes to the README's "Known issues" (no AWS access needed).

    pip install pytest moto
    pytest -q tests/test_known_issues.py

Covers: delivery-date eligibility, reply sanitising, explicit-return intent, the
refund backstop, stable runtime session ids, multi-turn WorkflowState and the
AgentCore Memory wiring (including graceful degradation when not configured).
tests/test_agent.py (the course grading suite) is unchanged.
"""
import os, sys, json, uuid
from datetime import date, timedelta

# Offline: fake credentials + moto. Set before boto3 clients are created.
os.environ.update(AWS_ACCESS_KEY_ID='testing', AWS_SECRET_ACCESS_KEY='testing',
                  AWS_DEFAULT_REGION='us-east-1', AWS_REGION='us-east-1')
os.environ.pop('AWS_SESSION_TOKEN', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'infrastructure')]

import pytest
from moto import mock_aws

_mock = mock_aws()
_mock.start()
import boto3
import config
for attr, name in (('WORKFLOW_STATE_TABLE', 'ut-workflow-state'), ('ORDERS_TABLE', 'ut-orders'),
                   ('CUSTOMERS_TABLE', 'ut-customers')):
    setattr(config, attr, name)
import agent_orchestrator as ao
import seed_data

TODAY = date(2026, 9, 26)


@pytest.fixture(autouse=True)
def _no_memory(monkeypatch):
    monkeypatch.delenv('AGENTCORE_MEMORY_ID', raising=False)
    monkeypatch.delenv('AGENT_MEMORY_ENABLED', raising=False)


@pytest.fixture(scope='module')
def tables():
    ddb = boto3.resource('dynamodb', region_name='us-east-1')
    ddb.create_table(TableName=config.WORKFLOW_STATE_TABLE, BillingMode='PAY_PER_REQUEST',
                     KeySchema=[{'AttributeName': 'session_id', 'KeyType': 'HASH'}],
                     AttributeDefinitions=[{'AttributeName': 'session_id', 'AttributeType': 'S'}])
    ddb.create_table(TableName=config.ORDERS_TABLE, BillingMode='PAY_PER_REQUEST',
                     KeySchema=[{'AttributeName': 'customer_id', 'KeyType': 'HASH'},
                                {'AttributeName': 'order_id', 'KeyType': 'RANGE'}],
                     AttributeDefinitions=[{'AttributeName': 'customer_id', 'AttributeType': 'S'},
                                           {'AttributeName': 'order_id', 'AttributeType': 'S'}])
    ddb.create_table(TableName=config.CUSTOMERS_TABLE, BillingMode='PAY_PER_REQUEST',
                     KeySchema=[{'AttributeName': 'customer_id', 'KeyType': 'HASH'}],
                     AttributeDefinitions=[{'AttributeName': 'customer_id', 'AttributeType': 'S'}])
    for o in seed_data.generate_orders():
        ddb.Table(config.ORDERS_TABLE).put_item(Item=o)
    for c in seed_data.CUSTOMERS if hasattr(seed_data, 'CUSTOMERS') else []:
        ddb.Table(config.CUSTOMERS_TABLE).put_item(Item=c)
    ddb.Table(config.CUSTOMERS_TABLE).put_item(Item={'customer_id': 'CUST-001', 'name': 'Alice', 'tier': 'Premium'})
    return ddb


# ── Fix 3: return window counted from delivery ───────────────────────────────
def _order(**kw):
    base = {'order_id': 'ORD-1', 'status': 'delivered'}
    base.update(kw)
    return base


def test_eligibility_uses_delivered_date():
    o = _order(order_date=str(TODAY - timedelta(days=33)), delivered_date=str(TODAY - timedelta(days=28)))
    r = ao._compute_eligibility(o, {'tier': 'Standard'}, today=TODAY)
    assert r['eligible'] and r['days_since_delivery'] == 28 and r['date_basis'] == 'delivered_date'
    assert r['days_since_order'] == 33          # would have been refused when counted from the order


def test_eligibility_fallbacks():
    est = ao._compute_eligibility(_order(order_date=str(TODAY - timedelta(days=40)),
                                         estimated_delivery=str(TODAY - timedelta(days=35))),
                                  {'tier': 'Premium'}, today=TODAY)
    assert est['date_basis'] == 'estimated_delivery' and est['days_since_delivery'] == 35
    future_est = ao._compute_eligibility(_order(order_date=str(TODAY - timedelta(days=2)),
                                                estimated_delivery=str(TODAY + timedelta(days=3))),
                                         {'tier': 'Standard'}, today=TODAY)
    assert future_est['date_basis'] == 'order_date' and future_est['eligible']
    none = ao._compute_eligibility(_order(), {'tier': 'Standard'}, today=TODAY)
    assert not none['eligible']
    shipped = ao._compute_eligibility(_order(status='shipped', order_date=str(TODAY)), {}, today=TODAY)
    assert not shipped['eligible'] and 'only delivered' in shipped['reason']


def test_seed_verdicts_unchanged():
    tiers = {'CUST-001': 'Premium', 'CUST-002': 'Standard', 'CUST-003': 'Premium', 'CUST-004': 'Standard'}
    verdict = {o['order_id']: ao._compute_eligibility(o, {'tier': tiers[o['customer_id']]})['eligible']
               for o in seed_data.generate_orders()}
    assert verdict['ORD-27176'] and verdict['ORD-28002'] and verdict['ORD-29001'] and verdict['ORD-30001']
    assert not verdict['ORD-27180'] and not verdict['ORD-28001'] and not verdict['ORD-29002']
    assert not verdict['ORD-29003'] and not verdict['ORD-28003']
    # seed_data.py is kept identical to the starter, so seeded orders carry no
    # delivered_date; eligibility falls back to estimated_delivery.


# ── Fix 5: only the customer-facing reply is returned ────────────────────────
MATH_LEAK = """I can see that this is a pricing calculation question, and the workflow context shows that no other agents (inventory, policy, or refund) have processed this request.

Let me provide a helpful response to the customer's calculation question:

---

**Subject: Your Pricing Question**

Hello,

Your total is **$134.96**.

Best regards,
**NovaMart Support**"""

RETURN_LEAK = """Based on the workflow context, I can see that the return has been approved. Let me compose the final response:

---

Dear Alice,

Your return is approved.

Warm regards,
NovaMart Support

---"""


def test_sanitiser_strips_reasoning():
    out = ao._final_customer_text(MATH_LEAK)
    assert out.startswith('Hello,') and '$134.96' in out
    assert 'workflow' not in out.lower() and 'Subject' not in out and '---' not in out
    out2 = ao._final_customer_text(RETURN_LEAK)
    assert out2.startswith('Dear Alice,') and out2.rstrip().endswith('NovaMart Support')


def test_sanitiser_keeps_clean_reply():
    clean = "Hello Bob,\n\nThank you for your question. Premium customers have 60 days.\n\nNovaMart Support"
    assert ao._final_customer_text(clean) == clean


# ── Fix 4: explicit return intent + deterministic backstop ───────────────────
@pytest.mark.parametrize('text,expected', [
    ("I want to return my wireless headphones from order ORD-27176", True),
    ("Please start a return for ORD-28002", True),
    ("I'd like to return order ORD-30001, it's the wrong colour", True),
    ("What is the return policy for premium customers?", False),
    ("Can I return my order ORD-27176?", False),
    ("How much would 5 items at $29.99 be with a 10% discount?", False),
])
def test_explicit_return_intent(text, expected):
    assert ao._explicit_return_intent(text) is expected


def test_refund_backstop_initiates_return(tables, monkeypatch):
    """The refund LLM only checks eligibility and asks for a reason; the backstop starts the return."""
    from strands.models import Model

    class AskReasonModel(Model):
        def __init__(self, **kw): self.config = kw
        def update_config(self, **kw): self.config.update(kw)
        def get_config(self): return self.config
        async def structured_output(self, *a, **k):
            raise NotImplementedError
            yield
        async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
            used = any('toolResult' in c for m in messages for c in m['content'])
            yield {'messageStart': {'role': 'assistant'}}
            if not used:
                sid = messages[0]['content'][0]['text'].split('[Session ID: ')[1].split(']')[0]
                yield {'contentBlockStart': {'start': {'toolUse': {'name': 'get_inventory_context',
                                                                   'toolUseId': 't1'}}}}
                yield {'contentBlockDelta': {'delta': {'toolUse': {'input': json.dumps(
                    {'session_id': sid, 'order_id': 'ORD-27176'})}}}}
                yield {'contentBlockStop': {}}
                yield {'messageStop': {'stopReason': 'tool_use'}}
            else:
                yield {'contentBlockDelta': {'delta': {'text': 'Eligible. Could you share the reason?'}}}
                yield {'contentBlockStop': {}}
                yield {'messageStop': {'stopReason': 'end_turn'}}

    monkeypatch.setattr(ao, 'BedrockModel', lambda **kw: AskReasonModel(**kw))
    refund = ao.build_refund_agent()
    dummy = ao.Agent(model=AskReasonModel(), tools=[])
    orch = ao.build_orchestrator_agent(dummy, refund, dummy, dummy)
    route = orch.tool_registry.registry['route_to_refund_agent']
    fn = getattr(route, '_tool_func', route)
    sid = 'ut' + uuid.uuid4().hex[:6]
    ao._begin_turn(sid, 'CUST-001', 'return')
    text = fn(session_id=sid, customer_id='CUST-001',
              request='I want to return my wireless headphones from order ORD-27176')
    item = tables.Table(config.ORDERS_TABLE).get_item(
        Key={'customer_id': 'CUST-001', 'order_id': 'ORD-27176'})['Item']
    assert item['status'] == 'Return Initiated' and item['return_reference'].startswith('RET-27176-')
    assert item['return_reference'] in text


# ── Fix 2: stable runtime session + multi-turn WorkflowState ─────────────────
def test_runtime_session_id_stable():
    a, b = ao._runtime_session_id('abc12345'), ao._runtime_session_id('abc12345')
    assert a == b and len(a) >= 33 and a != ao._runtime_session_id('abc12346')


def test_begin_turn_resets_agent_columns(tables):
    sid = 'turn' + uuid.uuid4().hex[:4]
    s1 = ao._begin_turn(sid, 'CUST-001', 'first', '')
    assert int(s1['turn']) == 1
    ao._update_workflow_state(sid, {'refund_agent': 'old', 'policy_agent': 'old'}, int(s1['version']))
    s2 = ao._begin_turn(sid, 'CUST-001', 'second', 'Customer: first')
    assert int(s2['turn']) == 2 and 'refund_agent' not in s2 and 'policy_agent' not in s2
    assert s2['memory_context'] == 'Customer: first' and s2['current_request'] == 'second'
    assert 'Customer: first' in ao._with_context(sid, 'second')


# ── Fix 1: AgentCore Memory wiring ───────────────────────────────────────────
class FakeMemory:
    def __init__(self): self.events = []
    def create_event(self, **kw): self.events.append(kw); return {'event': {'eventId': 'e1'}}
    def list_events(self, **kw):
        return {'events': [{'eventTimestamp': '2026-09-26T10:00:00Z', 'payload': [
            {'conversational': {'role': 'USER', 'content': {'text': 'I want to return ORD-27176'}}},
            {'conversational': {'role': 'ASSISTANT', 'content': {'text': 'Return RET-27176-1 started.'}}}]}]}
    def list_memory_records(self, **kw):
        assert kw['namespace'] == '/summaries/CUST-001/'
        return {'memoryRecordSummaries': [
            {'namespaces': ['/summaries/CUST-001/old1'], 'content': {'text': 'Asked about warranty.'}},
            {'namespaces': ['/summaries/CUST-001/s1'], 'content': {'text': 'current session summary'}}]}


def test_memory_disabled_is_noop(monkeypatch):
    class Boom:
        def __getattr__(self, n): raise AssertionError('memory API must not be called')
    monkeypatch.setattr(ao, 'agentcore_client', Boom())
    assert ao._load_memory_context('s1', 'CUST-001') == ''
    assert ao._save_memory_turn('s1', 'CUST-001', 'hi', 'hello') is False


def test_memory_load_and_save(monkeypatch):
    fake = FakeMemory()
    monkeypatch.setattr(ao, 'agentcore_client', fake)
    monkeypatch.setenv('AGENTCORE_MEMORY_ID', 'mem-123')
    ctx = ao._load_memory_context('s1', 'CUST-001')
    assert 'Customer: I want to return ORD-27176' in ctx and 'NovaMart: Return RET-27176-1' in ctx
    assert 'Asked about warranty.' in ctx and 'current session summary' not in ctx
    assert ao._save_memory_turn('s1', 'CUST-001', 'q', 'a') is True
    ev = fake.events[-1]
    assert ev['memoryId'] == 'mem-123' and ev['actorId'] == 'CUST-001' and ev['sessionId'] == 's1'
    assert [p['conversational']['role'] for p in ev['payload']] == ['USER', 'ASSISTANT']
    monkeypatch.setenv('AGENT_MEMORY_ENABLED', 'false')
    assert ao._memory_id() is None


def test_memory_errors_degrade(monkeypatch):
    class Failing:
        def __getattr__(self, n):
            def f(**kw): raise RuntimeError('AccessDenied')
            return f
    monkeypatch.setattr(ao, 'agentcore_client', Failing())
    monkeypatch.setenv('AGENTCORE_MEMORY_ID', 'mem-123')
    assert ao._load_memory_context('s1', 'CUST-001') == ''
    assert ao._save_memory_turn('s1', 'CUST-001', 'q', 'a') is False
