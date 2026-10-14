"""Stand-out extra (b): show the Strands DynamoDB session store recalling an earlier message.

    python scripts/session_store_demo.py write <session-id>   # turn 1 (process 1)
    python scripts/session_store_demo.py read  <session-id>   # new process, same session id

Uses the same functions the orchestrator calls each turn (_save_session_turn /
_load_session_history) against the live <project>-agent-sessions table.
"""
import os, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src')]
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, '.env'))
import boto3
import agent_orchestrator as ao

mode, sid = sys.argv[1], sys.argv[2]
if mode == 'write':
    user = "Hi, I'm Thandi. I want to return the phone case from order ORD-30001 - wrong colour."
    reply = "Thanks Thandi - your phone case from ORD-30001 is eligible; return reference RET-30001-DEMO."
    print(f"Table: {ao._sessions_table_name()}   session: {sid}")
    print(f"Customer: {user}\nNovaMart: {reply}")
    print("saved:", ao._save_session_turn(sid, user, reply))
else:
    agent = ao._conversation_agent(sid)          # fresh Strands Agent + RepositorySessionManager
    print(f"New process, same session id {sid}: Strands restored {len(agent.messages)} messages from DynamoDB")
    print(ao._load_session_history(sid))
    print("\nContext the orchestrator receives for the follow-up 'What was my return reference again?':")
    os.environ['AGENT_MEMORY_ENABLED'] = 'false'   # prove recall without AgentCore Memory
    ao._begin_turn = lambda *a, **k: {}
    print(ao._prepare_turn(sid, 'CUST-004', 'What was my return reference again?'))
    t = boto3.resource('dynamodb').Table(ao._sessions_table_name())
    items = t.query(KeyConditionExpression=boto3.dynamodb.conditions.Key('pk').eq(sid))['Items']
    print(f"\nDynamoDB items for pk={sid}:")
    for i in items: print(f"  sk={i['sk']:<40} {json.loads(i['data']).get('message', {}).get('role', '')}")
