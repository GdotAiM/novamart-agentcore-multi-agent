"""NovaMart frontend proxy (Lambda function URL).

1. Verifies the caller's Cognito *access token* with cognito-idp GetUser (Cognito
   checks signature, expiry and revocation) and reads custom:customer_id from the
   user's attributes. The customer id is never taken from the request body.
2. Invokes the AgentCore Runtime with this function's IAM role (SigV4), using the
   same payload / runtimeSessionId scheme as invoke_agent() in src/agent_orchestrator.py.
   The browser's session id is namespaced with the Cognito user's sub, so one user
   cannot continue another user's session.
"""
import hashlib, json, os, re
import boto3

RUNTIME_ARN = os.environ['AGENTCORE_RUNTIME_ARN']
REGION = os.environ.get('AWS_REGION', 'us-east-1')
idp = boto3.client('cognito-idp', region_name=REGION)
agentcore = boto3.client('bedrock-agentcore', region_name=REGION)


def _resp(code, body):
    return {'statusCode': code, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps(body)}


def handler(event, context):
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return _resp(204, {})
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
    token = headers.get('authorization', '').removeprefix('Bearer ').strip()
    if not token:
        return _resp(401, {'error': 'missing bearer token'})
    try:
        user = idp.get_user(AccessToken=token)
    except idp.exceptions.NotAuthorizedException:
        return _resp(401, {'error': 'invalid or expired token'})
    attrs = {a['Name']: a['Value'] for a in user['UserAttributes']}
    customer_id = attrs.get('custom:customer_id')
    if not customer_id:
        return _resp(403, {'error': 'user has no customer_id'})
    try:
        body = json.loads(event.get('body') or '{}')
    except ValueError:
        return _resp(400, {'error': 'invalid JSON'})
    prompt = (body.get('prompt') or '').strip()[:4000]
    tab = re.sub(r'[^A-Za-z0-9]', '', body.get('session_id') or '')[:16] or 'default'
    if not prompt:
        return _resp(400, {'error': 'prompt required'})
    session_id = f"web{hashlib.sha256((attrs['sub'] + tab).encode()).hexdigest()[:10]}"
    runtime_session_id = f"{session_id}-{hashlib.sha256(session_id.encode()).hexdigest()[:32]}"
    r = agentcore.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN, runtimeSessionId=runtime_session_id,
        contentType='application/json', accept='application/json',
        payload=json.dumps({'prompt': prompt, 'session_id': session_id, 'customer_id': customer_id}))
    raw = r['response'].read()
    try:
        out = json.loads(raw)
    except ValueError:
        out = {'result': raw.decode('utf-8', 'replace')}
    return _resp(200, {'reply': out.get('result', ''), 'session_id': session_id, 'turn': out.get('turn'),
                       'customer_id': customer_id, 'name': attrs.get('name', ''), 'trace_id': out.get('trace_id')})
