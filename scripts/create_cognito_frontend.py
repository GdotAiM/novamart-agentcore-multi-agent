"""Stand-out extra #4: Cognito customer auth + frontend proxy to the AgentCore Runtime.

Creates (idempotent, all additive - the starter stack is not touched):
  * Cognito user pool `novamart-customers` with custom attribute customer_id
    (read-only for the app client) and a public app client (no secret)
  * test users alice (CUST-001, Premium) and bob (CUST-002, Standard); passwords are
    generated and written ONLY to frontend/.cognito-test-user (gitignored)
  * IAM role `novamart-frontend-proxy-role` (InvokeAgentRuntime on this runtime + logs)
  * Lambda `novamart-frontend-proxy` + function URL (CORS) - see frontend/proxy/handler.py
  * frontend/config.js (pool/client ids + proxy URL; ids only, no secrets)

    python scripts/create_cognito_frontend.py            # create / update
    python scripts/create_cognito_frontend.py --delete   # remove everything above
"""
import io, json, os, secrets, string, sys, time, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, '.env'))
import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get('AWS_REGION', 'us-east-1')
POOL, CLIENT = 'novamart-customers', 'novamart-web'
ROLE, FN = 'novamart-frontend-proxy-role', 'novamart-frontend-proxy'
ORIGINS = ['http://localhost:8765', 'http://127.0.0.1:8765']
USERS = [('alice', 'Alice Johnson', 'CUST-001', 'Premium'), ('bob', 'Bob Smith', 'CUST-002', 'Standard')]
FRONT = os.path.join(ROOT, 'frontend')
idp, iam, lam = boto3.client('cognito-idp', region_name=REGION), boto3.client('iam'), boto3.client('lambda', region_name=REGION)


def find_pool():
    for p in idp.list_user_pools(MaxResults=60)['UserPools']:
        if p['Name'] == POOL:
            return p['Id']


def delete():
    for f in (lambda: lam.delete_function(FunctionName=FN),
              lambda: iam.delete_role_policy(RoleName=ROLE, PolicyName='invoke-runtime'),
              lambda: iam.delete_role(RoleName=ROLE)):
        try: f()
        except ClientError as e: print('skip:', e.response['Error']['Code'])
    pid = find_pool()
    if pid:
        idp.delete_user_pool(UserPoolId=pid)
    print('deleted')


def password():
    a = string.ascii_letters + string.digits
    return 'Nm-' + ''.join(secrets.choice(a) for _ in range(16)) + '7a!'


def main():
    if '--delete' in sys.argv:
        return delete()
    account = boto3.client('sts').get_caller_identity()['Account']
    runtime_arn = os.environ['AGENTCORE_RUNTIME_ARN']
    pid = find_pool()
    if not pid:
        pid = idp.create_user_pool(
            PoolName=POOL, UsernameConfiguration={'CaseSensitive': False},
            Policies={'PasswordPolicy': {'MinimumLength': 12, 'RequireUppercase': True, 'RequireLowercase': True,
                                         'RequireNumbers': True, 'RequireSymbols': True}},
            AdminCreateUserConfig={'AllowAdminCreateUserOnly': True},
            Schema=[{'Name': 'customer_id', 'AttributeDataType': 'String', 'Mutable': True,
                     'StringAttributeConstraints': {'MinLength': '1', 'MaxLength': '32'}},
                    {'Name': 'tier', 'AttributeDataType': 'String', 'Mutable': True}],
            )['UserPool']['Id']
    cid = next((c['ClientId'] for c in idp.list_user_pool_clients(UserPoolId=pid, MaxResults=60)['UserPoolClients']
                if c['ClientName'] == CLIENT), None)
    if not cid:
        cid = idp.create_user_pool_client(
            UserPoolId=pid, ClientName=CLIENT, GenerateSecret=False,
            ExplicitAuthFlows=['ALLOW_USER_PASSWORD_AUTH', 'ALLOW_USER_SRP_AUTH', 'ALLOW_REFRESH_TOKEN_AUTH'],
            ReadAttributes=['name', 'custom:customer_id', 'custom:tier'], WriteAttributes=['name'],
            AccessTokenValidity=60, IdTokenValidity=60, TokenValidityUnits={'AccessToken': 'minutes', 'IdToken': 'minutes'},
            PreventUserExistenceErrors='ENABLED')['UserPoolClient']['ClientId']
    creds = {}
    for user, name, cust, tier in USERS:
        attrs = [{'Name': 'name', 'Value': name}, {'Name': 'custom:customer_id', 'Value': cust},
                 {'Name': 'custom:tier', 'Value': tier}]
        # AdminSetUserPassword is not permitted in the lab, so: (re)create the user with a
        # temporary password and answer NEW_PASSWORD_REQUIRED through the public client flow.
        try:
            idp.admin_delete_user(UserPoolId=pid, Username=user)
        except idp.exceptions.UserNotFoundException:
            pass
        tmp, pw = password(), password()
        idp.admin_create_user(UserPoolId=pid, Username=user, UserAttributes=attrs,
                              TemporaryPassword=tmp, MessageAction='SUPPRESS')
        ch = idp.initiate_auth(ClientId=cid, AuthFlow='USER_PASSWORD_AUTH',
                               AuthParameters={'USERNAME': user, 'PASSWORD': tmp})
        assert ch.get('ChallengeName') == 'NEW_PASSWORD_REQUIRED', ch.get('ChallengeName')
        idp.respond_to_auth_challenge(ClientId=cid, ChallengeName='NEW_PASSWORD_REQUIRED', Session=ch['Session'],
                                      ChallengeResponses={'USERNAME': user, 'NEW_PASSWORD': pw})
        creds[user] = {'password': pw, 'customer_id': cust, 'tier': tier, 'name': name}
    path = os.path.join(FRONT, '.cognito-test-user')
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
        json.dump(creds, f, indent=2)

    trust = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow', 'Principal': {'Service': 'lambda.amazonaws.com'},
                                                     'Action': 'sts:AssumeRole'}]}
    try:
        role_arn = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust))['Role']['Arn']
        time.sleep(10)
    except iam.exceptions.EntityAlreadyExistsException:
        role_arn = iam.get_role(RoleName=ROLE)['Role']['Arn']
    iam.put_role_policy(RoleName=ROLE, PolicyName='invoke-runtime', PolicyDocument=json.dumps({
        'Version': '2012-10-17', 'Statement': [
            {'Effect': 'Allow', 'Action': 'bedrock-agentcore:InvokeAgentRuntime',
             'Resource': [runtime_arn, runtime_arn + '/*']},
            {'Effect': 'Allow', 'Action': ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
             'Resource': f'arn:aws:logs:{REGION}:{account}:log-group:/aws/lambda/{FN}*'}]}))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.write(os.path.join(FRONT, 'proxy', 'handler.py'), 'handler.py')
    env = {'Variables': {'AGENTCORE_RUNTIME_ARN': runtime_arn}}
    for attempt in range(6):
        try:
            try:
                lam.create_function(FunctionName=FN, Runtime='python3.12', Role=role_arn, Handler='handler.handler',
                                    Code={'ZipFile': buf.getvalue()}, Timeout=120, MemorySize=256, Environment=env,
                                    Architectures=['arm64'], Tags={'project': 'udacity-agentcore'})
            except lam.exceptions.ResourceConflictException:
                lam.update_function_code(FunctionName=FN, ZipFile=buf.getvalue())
                lam.get_waiter('function_updated_v2').wait(FunctionName=FN)
                lam.update_function_configuration(FunctionName=FN, Environment=env, Timeout=120)
            break
        except lam.exceptions.InvalidParameterValueException:
            time.sleep(10)                                   # new role not yet assumable
    lam.get_waiter('function_active_v2').wait(FunctionName=FN)
    cors = {'AllowOrigins': ORIGINS, 'AllowMethods': ['POST'], 'AllowHeaders': ['authorization', 'content-type'], 'MaxAge': 3600}
    try:
        url = lam.create_function_url_config(FunctionName=FN, AuthType='NONE', Cors=cors)['FunctionUrl']
    except lam.exceptions.ResourceConflictException:
        lam.get_waiter('function_updated_v2').wait(FunctionName=FN)
        url = lam.update_function_url_config(FunctionName=FN, AuthType='NONE', Cors=cors)['FunctionUrl']
    for sid, action in (('public-url', 'lambda:InvokeFunctionUrl'), ('public-invoke', 'lambda:InvokeFunction')):
        try:
            kw = {'FunctionUrlAuthType': 'NONE'} if action == 'lambda:InvokeFunctionUrl' else {'InvokedViaFunctionUrl': True}
            lam.add_permission(FunctionName=FN, StatementId=sid, Action=action, Principal='*', **kw)
        except lam.exceptions.ResourceConflictException:
            pass
        except Exception as e:
            print(f'add_permission {action}: {e}')
    with open(os.path.join(FRONT, 'config.js'), 'w') as f:
        f.write('// Generated by scripts/create_cognito_frontend.py (resource ids only, no secrets)\n'
                f"window.NOVAMART = {json.dumps({'region': REGION, 'userPoolId': pid, 'clientId': cid, 'proxyUrl': url}, indent=2)};\n")
    print(f'User pool: {pid}\nApp client: {cid}\nProxy role: {role_arn}\nProxy URL: {url}')
    print(f'Test users: {", ".join(u[0] + " (" + u[2] + ", " + u[3] + ")" for u in USERS)}; passwords in frontend/.cognito-test-user')


if __name__ == '__main__':
    main()
