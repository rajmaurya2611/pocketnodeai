import threading
import time

def test_auth_and_persistence(client, admin_headers, registered):
    device,key=registered
    assert client.get('/admin/devices').status_code==401
    assert client.get('/v1/device/status',headers={'Authorization':'Bearer '+key['api_key']}).json()['online'] is False
    assert client.post('/v1/chat/completions',headers={'Authorization':'Bearer '+key['api_key']},json={
        'model':'qwen3-0.6b','messages':[{'role':'user','content':'Hi'}]}).status_code==503
    rotated=client.post('/admin/keys/'+key['key_id']+'/rotate',headers=admin_headers).json()
    assert rotated['api_key']!=key['api_key']
    assert client.get('/v1/models',headers={'Authorization':'Bearer '+key['api_key']}).status_code==401
    assert client.get('/v1/models',headers={'Authorization':'Bearer '+rotated['api_key']}).status_code==200


def test_end_to_end_websocket(client, registered):
    device,key=registered
    headers={'Authorization':'Bearer '+key['api_key']}
    with client.websocket_connect('/ws/worker',headers={'Authorization':'Bearer '+device['device_token']}) as ws:
        assert ws.receive_json()['type']=='connected'
        ws.send_json({'type':'ready','model':'qwen3-0.6b','capabilities':{'context_window':4096,'max_output_tokens':1024}})
        assert ws.receive_json()['type']=='ready_ack'
        assert client.get('/v1/device/status',headers=headers).json()['ready'] is True
        result={}
        def call_client():
            result['response']=client.post('/v1/chat/completions',headers=headers,json={
                'model':'qwen3-0.6b','messages':[{'role':'user','content':'Hi worker'}],'max_tokens':128})
        thread=threading.Thread(target=call_client)
        thread.start()
        message=ws.receive_json()
        assert message['type']=='inference_request'
        assert message['messages'][0]['content']=='Hi worker'
        ws.send_json({'type':'inference_result','request_id':message['request_id'],'status':'completed',
                      'output':'Hello from real worker protocol',
                      'usage':{'prompt_tokens':2,'completion_tokens':5}})
        thread.join(timeout=5)
        assert not thread.is_alive()
        response=result['response']
        assert response.status_code==200, response.text
        body=response.json()
        assert body['choices'][0]['message']['content']=='Hello from real worker protocol'
        assert body['usage']['total_tokens']==7
    assert client.get('/v1/device/status',headers=headers).json()['online'] is False


def test_limits(client,registered):
    device,key=registered
    with client.websocket_connect('/ws/worker',headers={'Authorization':'Bearer '+device['device_token']}) as ws:
        ws.receive_json()
        ws.send_json({'type':'ready','model':'qwen3-0.6b','capabilities':{'context_window':2048,'max_output_tokens':256}})
        ws.receive_json()
        response=client.post('/v1/chat/completions',headers={'Authorization':'Bearer '+key['api_key']},json={
            'model':'qwen3-0.6b','max_tokens':999,'messages':[{'role':'user','content':'Hello'}]})
        assert response.status_code==422
