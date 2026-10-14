"""Headless end-to-end check of extra #4 (same HTTP calls the browser makes).

Signs in as a Cognito test user (password read from frontend/.cognito-test-user, never
printed), sends a return request and a follow-up in one session via the proxy, and checks
that requests without / with a bad token are rejected and that CORS preflight works.

    python scripts/frontend_e2e_check.py [alice|bob]
"""
import json, os, re, sys, time, urllib.request, urllib.error, uuid
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cfg = json.loads(re.search(r'=\s*(\{.*\});', open(os.path.join(ROOT, 'frontend', 'config.js')).read(), re.S).group(1))
users = json.load(open(os.path.join(ROOT, 'frontend', '.cognito-test-user')))
user = sys.argv[1] if len(sys.argv) > 1 else 'alice'


def post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


s, auth = post(f"https://cognito-idp.{cfg['region']}.amazonaws.com/",
               {'AuthFlow': 'USER_PASSWORD_AUTH', 'ClientId': cfg['clientId'],
                'AuthParameters': {'USERNAME': user, 'PASSWORD': users[user]['password']}},
               {'Content-Type': 'application/x-amz-json-1.1',
                'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth'})
assert s == 200, (s, auth.get('message'))
tok = auth['AuthenticationResult']['AccessToken']
print(f"Cognito sign-in as '{user}': OK (access token {len(tok)} chars, not shown)")
H = {'Content-Type': 'application/json', 'Origin': 'http://localhost:8765'}
print('No token  ->', post(cfg['proxyUrl'], {'prompt': 'hi'}, H)[0])
print('Bad token ->', post(cfg['proxyUrl'], {'prompt': 'hi'}, {**H, 'Authorization': 'Bearer abc.def.ghi'})[0])
req = urllib.request.Request(cfg['proxyUrl'], method='OPTIONS', headers={
    'Origin': 'http://localhost:8765', 'Access-Control-Request-Method': 'POST',
    'Access-Control-Request-Headers': 'authorization,content-type'})
with urllib.request.urlopen(req) as r:
    print('CORS preflight ->', r.status, r.headers.get('Access-Control-Allow-Origin'))
tab = uuid.uuid4().hex[:12]
turns = {'alice': ["I want to return my wireless headphones from order ORD-27176", "What was my return reference again?"],
         'bob': ["Is my running shoes order ORD-28002 eligible for a return?", "And how long do I have to send it back?"]}[user]
for i, prompt in enumerate(turns, 1):
    t0 = time.time()
    s, out = post(cfg['proxyUrl'], {'prompt': prompt, 'session_id': tab}, {**H, 'Authorization': f'Bearer {tok}'})
    print(f"\n--- turn {i} (HTTP {s}, {time.time() - t0:.1f}s, customer {out.get('customer_id')} from token, "
          f"session {out.get('session_id')}, turn {out.get('turn')})\nCustomer: {prompt}\nNovaMart: {out.get('reply') or out}")
    assert s == 200
