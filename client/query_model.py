"""Run from root after setting POCKETNODE_API_KEY in environment."""
import os
import sys
from openai import OpenAI

client=OpenAI(api_key=os.environ['POCKETNODE_API_KEY'],base_url=os.getenv('POCKETNODE_API_BASE','http://127.0.0.1:8000/v1'),max_retries=0,timeout=130)
prompt=' '.join(sys.argv[1:]) or 'Explain what an LLM is in two sentences.'
response=client.chat.completions.create(model='qwen3-0.6b',messages=[{'role':'user','content':prompt}],max_tokens=256,stream=False)
print(response.choices[0].message.content)
