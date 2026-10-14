"""
Offline (moto) tests for the Strands DynamoDB session store (stand-out extra b).

    pytest -q tests/test_session_store.py
"""
import os, sys

os.environ.update(AWS_ACCESS_KEY_ID='testing', AWS_SECRET_ACCESS_KEY='testing',
                  AWS_DEFAULT_REGION='us-east-1', AWS_REGION='us-east-1',
                  AGENT_SESSIONS_TABLE='ut-agent-sessions')
os.environ.pop('AWS_SESSION_TOKEN', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'infrastructure')]

import pytest
from moto import mock_aws

_mock = mock_aws()
_mock.start()
import boto3
import agent_orchestrator as ao
from strands.session import SessionRepository, RepositorySessionManager
from strands.types.session import Session, SessionType, SessionAgent, SessionMessage
from strands.types.exceptions import SessionException


@pytest.fixture(scope='module', autouse=True)
def table():
    ddb = boto3.resource('dynamodb', region_name='us-east-1')
    try:
        ddb.create_table(TableName='ut-agent-sessions', BillingMode='PAY_PER_REQUEST',
                         KeySchema=[{'AttributeName': 'pk', 'KeyType': 'HASH'},
                                    {'AttributeName': 'sk', 'KeyType': 'RANGE'}],
                         AttributeDefinitions=[{'AttributeName': 'pk', 'AttributeType': 'S'},
                                               {'AttributeName': 'sk', 'AttributeType': 'S'}])
    except Exception:
        pass
    yield


def repo():
    return ao.DynamoDBSessionRepository(resource=boto3.resource('dynamodb', region_name='us-east-1'))


def test_is_a_strands_session_repository():
    assert isinstance(repo(), SessionRepository)
    assert ao._sessions_table_name() == 'ut-agent-sessions'


def test_session_crud_and_duplicate():
    r = repo()
    r.create_session(Session(session_id='s-crud', session_type=SessionType.AGENT))
    assert r.read_session('s-crud').session_id == 's-crud'
    assert r.read_session('missing') is None
    with pytest.raises(SessionException):
        r.create_session(Session(session_id='s-crud', session_type=SessionType.AGENT))


def test_messages_are_ordered_and_paginated():
    r = repo()
    for i in (2, 0, 11, 1):
        r.create_message('s-msg', 'a1', SessionMessage(
            message={'role': 'user', 'content': [{'text': f'm{i}'}]}, message_id=i))
    ids = [m.message_id for m in r.list_messages('s-msg', 'a1')]
    assert ids == [0, 1, 2, 11]
    assert [m.message_id for m in r.list_messages('s-msg', 'a1', limit=2, offset=1)] == [1, 2]
    assert r.list_messages('s-msg', 'other') == []


def test_update_message_requires_existing():
    r = repo()
    with pytest.raises(SessionException):
        r.update_message('s-x', 'a1', SessionMessage(message={'role': 'user', 'content': []}, message_id=5))


def test_strands_session_manager_restores_agent_history():
    """Same session id -> a new Strands Agent recalls earlier messages from DynamoDB."""
    assert ao._save_session_turn('demo-1', 'My name is Thandi, order ORD-30001.', 'Thanks Thandi.')
    assert ao._save_session_turn('demo-1', 'What was my order again?', 'Your order is ORD-30001.')
    agent = ao._conversation_agent('demo-1')
    texts = [c['text'] for m in agent.messages for c in m['content']]
    assert texts[0] == 'My name is Thandi, order ORD-30001.'
    assert len(texts) == 4 and agent.messages[1]['role'] == 'assistant'
    history = ao._load_session_history('demo-1')
    assert 'Customer: My name is Thandi' in history and 'NovaMart: Your order is ORD-30001.' in history


def test_sessions_are_isolated():
    ao._save_session_turn('iso-a', 'secret A', 'ok')
    assert 'secret A' not in ao._load_session_history('iso-b')


def test_disabled_and_failure_never_raise(monkeypatch):
    monkeypatch.setenv('AGENT_SESSIONS_ENABLED', 'false')
    assert ao._load_session_history('demo-1') == ''
    assert ao._save_session_turn('demo-1', 'x', 'y') is False
    monkeypatch.setenv('AGENT_SESSIONS_ENABLED', 'true')
    monkeypatch.setenv('AGENT_SESSIONS_TABLE', 'does-not-exist')
    assert ao._load_session_history('demo-1') == ''
    assert ao._save_session_turn('demo-1', 'x', 'y') is False


def test_prepare_turn_includes_session_history_without_memory(monkeypatch):
    monkeypatch.delenv('AGENTCORE_MEMORY_ID', raising=False)
    monkeypatch.setattr(ao, '_begin_turn', lambda *a, **k: {})
    ao._save_session_turn('ctx-1', 'I bought a yoga mat', 'Noted.')
    prompt = ao._prepare_turn('ctx-1', 'CUST-004', 'what did I buy?')
    assert 'session store' in prompt and 'I bought a yoga mat' in prompt
    assert prompt.startswith('[Session ID: ctx-1] [Customer ID: CUST-004] what did I buy?')
