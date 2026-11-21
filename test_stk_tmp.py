import sys, json, os
with open('gateway/.env', encoding='utf-8-sig') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())
sys.path.insert(0, 'mcp/mpesa')
from server import stk_push
print(json.dumps(stk_push('254708374149', 10, 'ansai-test-001'), indent=2, ensure_ascii=False))
