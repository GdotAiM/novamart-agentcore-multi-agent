"""Stand-out extra (b): create the Strands session-store table and grant the runtime role access.

Additive to the starter stack (infrastructure/starter_stack.yaml is never modified):
  * DynamoDB table <PROJECT_NAME>-agent-sessions (pk/sk strings, on-demand, TTL on `ttl`)
  * inline IAM policy `NovaMartAgentSessionsAccess` on the stack's AgentCore execution role

    python scripts/create_agent_sessions_table.py            # create / ensure
    python scripts/create_agent_sessions_table.py --delete   # remove table + policy
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, '.env'))
import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get('AWS_REGION', 'us-east-1')
PROJECT = os.environ.get('PROJECT_NAME', 'udacity-agentcore')
TABLE = os.environ.get('AGENT_SESSIONS_TABLE') or f"{PROJECT}-agent-sessions"
ROLE = f"{PROJECT}-agentcore-role"
POLICY = 'NovaMartAgentSessionsAccess'


def main():
    ddb, iam = boto3.client('dynamodb', region_name=REGION), boto3.client('iam')
    account = boto3.client('sts').get_caller_identity()['Account']
    arn = f"arn:aws:dynamodb:{REGION}:{account}:table/{TABLE}"
    if '--delete' in sys.argv:
        for fn in (lambda: iam.delete_role_policy(RoleName=ROLE, PolicyName=POLICY),
                   lambda: ddb.delete_table(TableName=TABLE)):
            try: fn()
            except ClientError as e: print('skip:', e.response['Error']['Code'])
        print('deleted'); return
    try:
        ddb.create_table(TableName=TABLE, BillingMode='PAY_PER_REQUEST',
                         AttributeDefinitions=[{'AttributeName': 'pk', 'AttributeType': 'S'},
                                               {'AttributeName': 'sk', 'AttributeType': 'S'}],
                         KeySchema=[{'AttributeName': 'pk', 'KeyType': 'HASH'},
                                    {'AttributeName': 'sk', 'KeyType': 'RANGE'}],
                         Tags=[{'Key': 'project', 'Value': PROJECT}])
        print(f"Creating table {TABLE} ...")
    except ClientError as e:
        if e.response['Error']['Code'] != 'ResourceInUseException': raise
        print(f"Table {TABLE} already exists")
    ddb.get_waiter('table_exists').wait(TableName=TABLE)
    try:
        ddb.update_time_to_live(TableName=TABLE, TimeToLiveSpecification={'Enabled': True, 'AttributeName': 'ttl'})
    except ClientError as e:
        if 'already enabled' not in str(e): print('TTL:', e.response['Error']['Message'])
    doc = {'Version': '2012-10-17', 'Statement': [{
        'Sid': 'StrandsSessionStore', 'Effect': 'Allow',
        'Action': ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:UpdateItem',
                   'dynamodb:DeleteItem', 'dynamodb:Query'],
        'Resource': [arn]}]}
    iam.put_role_policy(RoleName=ROLE, PolicyName=POLICY, PolicyDocument=json.dumps(doc))
    print(f"Table ACTIVE: {arn}")
    print(f"Inline policy {POLICY} on role {ROLE}: {', '.join(doc['Statement'][0]['Action'])}")


if __name__ == '__main__':
    main()
