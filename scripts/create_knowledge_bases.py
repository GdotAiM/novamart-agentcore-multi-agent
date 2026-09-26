"""Create the 3 NovaMart Knowledge Bases on the stack's S3 Vectors store (API equivalent of the console wizard).

Run from the repo root after the stack is deployed and seeded:  python scripts/create_knowledge_bases.py
Creates (or reuses) novamart-{returns,shipping,warranty}-policy-kb, syncs each data source, waits for
completion and writes RETURNS_KB_ID / SHIPPING_KB_ID / WARRANTY_KB_ID into .env.
"""
import sys, os, time, re
sys.path.insert(0, os.getcwd())
import boto3, config
agent = boto3.client('bedrock-agent', region_name=config.AWS_REGION)
role = config.AGENTCORE_ROLE_ARN          # stack role: trusts bedrock.amazonaws.com, has InvokeModel, s3 read, s3vectors:*
bucket_arn = f"arn:aws:s3:::{config.POLICY_BUCKET}"
vb_arn = config.VECTOR_STORE_BUCKET_ARN
EMB = f"arn:aws:bedrock:{config.AWS_REGION}::foundation-model/amazon.titan-embed-text-v2:0"
specs = [('RETURNS_KB_ID', 'novamart-returns-policy-kb', 'policies/returns/', config.RETURNS_VECTOR_INDEX),
         ('SHIPPING_KB_ID', 'novamart-shipping-policy-kb', 'policies/shipping/', config.SHIPPING_VECTOR_INDEX),
         ('WARRANTY_KB_ID', 'novamart-warranty-policy-kb', 'policies/warranty/', config.WARRANTY_VECTOR_INDEX)]
existing = {k['name']: k['knowledgeBaseId'] for p in agent.get_paginator('list_knowledge_bases').paginate()
            for k in p['knowledgeBaseSummaries']}
print(f"KB service role : {role}\nData bucket     : {bucket_arn}\nVector bucket   : {vb_arn}\n")
ids = {}
for env_key, name, prefix, index in specs:
    if name in existing:
        kb_id = existing[name]; print(f"{name}: already exists ({kb_id})")
    else:
        kb = agent.create_knowledge_base(
            name=name, roleArn=role, description=f"NovaMart {prefix} policies",
            knowledgeBaseConfiguration={'type': 'VECTOR', 'vectorKnowledgeBaseConfiguration': {
                'embeddingModelArn': EMB,
                'embeddingModelConfiguration': {'bedrockEmbeddingModelConfiguration': {
                    'dimensions': 1024, 'embeddingDataType': 'FLOAT32'}}}},
            storageConfiguration={'type': 'S3_VECTORS', 's3VectorsConfiguration': {
                'vectorBucketArn': vb_arn, 'indexName': index}})['knowledgeBase']
        kb_id = kb['knowledgeBaseId']; print(f"{name}: created {kb_id} (index {index})")
    while True:
        st = agent.get_knowledge_base(knowledgeBaseId=kb_id)['knowledgeBase']['status']
        if st != 'CREATING': break
        time.sleep(5)
    print(f"  status: {st}")
    dss = agent.list_data_sources(knowledgeBaseId=kb_id)['dataSourceSummaries']
    if dss:
        ds_id = dss[0]['dataSourceId']
    else:
        ds_id = agent.create_data_source(knowledgeBaseId=kb_id, name=f"{name}-s3",
            dataSourceConfiguration={'type': 'S3', 's3Configuration': {
                'bucketArn': bucket_arn, 'inclusionPrefixes': [prefix]}})['dataSource']['dataSourceId']
    print(f"  data source {ds_id} -> s3://{config.POLICY_BUCKET}/{prefix}")
    ids[env_key] = (kb_id, ds_id, name)

print("\nSyncing (start_ingestion_job)...")
jobs = {k: agent.start_ingestion_job(knowledgeBaseId=v[0], dataSourceId=v[1])['ingestionJob']['ingestionJobId']
        for k, v in ids.items()}
for k, (kb_id, ds_id, name) in ids.items():
    while True:
        j = agent.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id, ingestionJobId=jobs[k])['ingestionJob']
        if j['status'] in ('COMPLETE', 'FAILED', 'STOPPED'): break
        time.sleep(5)
    s = j.get('statistics', {})
    print(f"  {name:30s} {kb_id}  sync {j['status']}  scanned={s.get('numberOfDocumentsScanned')} "
          f"indexed={s.get('numberOfNewDocumentsIndexed')} failed={s.get('numberOfDocumentsFailed')}"
          + (f"  reasons={j.get('failureReasons')}" if j.get('failureReasons') else ''))

env = open('.env').read()
for k, (kb_id, _, _) in ids.items():
    env = re.sub(rf'^{k}=.*$', f'{k}={kb_id}', env, flags=re.M)
open('.env', 'w').write(env)
print("\n.env updated:"); [print(f"  {k}={v[0]}") for k, v in ids.items()]
