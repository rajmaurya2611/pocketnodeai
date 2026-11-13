"""Run from project root with: python worker_simulator/mock_worker.py"""
import asyncio
import json
import os
from websockets.asyncio.client import connect

BASE = os.getenv('POCKETNODE_WS_URL','ws://127.0.0.1:8000/ws/worker')
TOKEN = os.environ['POCKETNODE_DEVICE_TOKEN']
MODEL = os.getenv('POCKETNODE_MODEL','qwen3-0.6b')

async def run():
    while True:
        try:
            async with connect(BASE,additional_headers={'Authorization':f'Bearer {TOKEN}'}) as ws:
                print('Connected to gateway')
                async for raw in ws:
                    message=json.loads(raw)
                    typ=message.get('type')
                    if typ=='connected':
                        await ws.send(json.dumps({'type':'ready','model':MODEL,
                            'capabilities':{'context_window':4096,'max_output_tokens':1024}}))
                    elif typ=='ready_ack': print('Worker READY')
                    elif typ=='inference_request':
                        user_text=' '.join(m['content'] for m in message['messages'] if m['role']=='user')
                        await ws.send(json.dumps({'type':'inference_result','request_id':message['request_id'],
                            'status':'completed', 'output':f'[MOCK PHONE] You said: {user_text}',
                            'finish_reason':'stop','usage':{'prompt_tokens':len(user_text.split()),'completion_tokens':12}}))
                    elif typ=='cancel_request': print('Cancelled by gateway',message.get('request_id'))
        except Exception as exc:
            print('Worker disconnected:',exc,'reconnecting in 3 seconds')
            await asyncio.sleep(3)

if __name__=='__main__':
    asyncio.run(run())
