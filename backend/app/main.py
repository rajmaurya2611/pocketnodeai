import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Header
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from . import models
from .config import get_settings
from .db import Base, engine, get_db, SessionLocal
from .registry import WorkerRegistry, WorkerSession, WorkerOffline, WorkerBusy, WorkerTimeout
from .schemas import RegisterDevice, IssueKey, ChatCompletionRequest
from .security import require_admin, issue_credential, check_device, check_api_key

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield
    for session in list(app.state.registry.sessions.values()):
        await app.state.registry.detach(session)

app = FastAPI(title="PocketNode AI Gateway", version="0.1.0", lifespan=lifespan)
app.state.registry = WorkerRegistry()

def public_device(device: models.Device):
    return {'device_id':device.id, 'name':device.name,'model_id':device.model_id,'revoked':device.revoked_at is not None}

def public_key(key: models.ApiKey):
    return {'key_id':key.id,'device_id':key.device_id,'label':key.label,'revoked':key.revoked_at is not None}

@app.get('/health')
def health():
    return {'status':'ok'}

@app.post('/admin/devices', dependencies=[Depends(require_admin)], status_code=201)
def register_device(data: RegisterDevice, db: Session = Depends(get_db)):
    identifier, token, hashed = issue_credential('pn_dev')
    device = models.Device(id=identifier, name=data.name, credential_hash=hashed, model_id=data.model_id)
    db.add(device); db.commit()
    return {**public_device(device), 'device_token': token, 'note':'Device token is returned only once. Store securely on phone.'}

@app.get('/admin/devices', dependencies=[Depends(require_admin)])
def list_devices(db: Session = Depends(get_db)):
    devices = db.scalars(select(models.Device)).all()
    return [{**public_device(d), **device_status(d.id)} for d in devices]

@app.post('/admin/keys', dependencies=[Depends(require_admin)], status_code=201)
def create_key(data: IssueKey, db: Session = Depends(get_db)):
    device = db.get(models.Device, data.device_id)
    if not device or device.revoked_at: raise HTTPException(404,'Device not registered')
    identifier, token, hashed = issue_credential('pn_sk')
    key = models.ApiKey(id=identifier, device_id=data.device_id, label=data.label, credential_hash=hashed)
    db.add(key); db.commit()
    return {**public_key(key), 'api_key':token, 'note':'API key shown only once.'}

@app.get('/admin/keys', dependencies=[Depends(require_admin)])
def list_keys(db: Session = Depends(get_db)):
    return [public_key(k) for k in db.scalars(select(models.ApiKey)).all()]

@app.post('/admin/keys/{key_id}/rotate', dependencies=[Depends(require_admin)])
def rotate_key(key_id: str, db: Session = Depends(get_db)):
    old = db.get(models.ApiKey,key_id)
    if not old or old.revoked_at: raise HTTPException(404,'Active key not found')
    identifier, token, hashed = issue_credential('pn_sk')
    successor = models.ApiKey(id=identifier,device_id=old.device_id,label=old.label,credential_hash=hashed)
    old.revoked_at=datetime.now(timezone.utc)
    db.add(successor); db.commit()
    return {**public_key(successor),'api_key':token,'replaced_key_id':key_id}

@app.delete('/admin/keys/{key_id}', dependencies=[Depends(require_admin)])
def revoke_key(key_id: str, db: Session = Depends(get_db)):
    key = db.get(models.ApiKey, key_id)
    if not key: raise HTTPException(404,'Key not found')
    key.revoked_at=datetime.now(timezone.utc)
    db.commit()
    return {'revoked':True,'key_id':key_id}

@app.post('/admin/devices/{device_id}/revoke', dependencies=[Depends(require_admin)])
async def revoke_device(device_id: str, db: Session = Depends(get_db)):
    device = db.get(models.Device,device_id)
    if not device: raise HTTPException(404,'Device not found')
    device.revoked_at=datetime.now(timezone.utc)
    for key in db.scalars(select(models.ApiKey).where(models.ApiKey.device_id==device_id)):
        key.revoked_at=datetime.now(timezone.utc)
    db.commit()
    sess=app.state.registry.get(device_id)
    if sess:
        await app.state.registry.detach(sess)
        try: await sess.socket.close(code=4003,reason='Device revoked')
        except Exception: pass
    return {'revoked':True,'device_id':device_id}

def device_status(device_id: str):
    session=app.state.registry.get(device_id)
    return {'online':bool(session), 'ready':bool(session and session.ready),
        'busy':bool(session and session.active),
        'capabilities':({'model':session.model_id,'context_window':session.context_window,
                         'max_output_tokens':session.max_output_tokens,'streaming':False} if session else None)}

@app.get('/admin/devices/{device_id}/status', dependencies=[Depends(require_admin)])
def admin_status(device_id: str,db:Session=Depends(get_db)):
    device=db.get(models.Device, device_id)
    if not device: raise HTTPException(404,'Device not found')
    return {**public_device(device), **device_status(device_id)}

@app.websocket('/ws/worker')
async def worker_websocket(ws: WebSocket):
    # Device token is passed in Authorization header, never in query string.
    authorization=ws.headers.get('authorization','')
    token=authorization[7:] if authorization.startswith('Bearer ') else None
    with SessionLocal() as db:
        device=check_device(db,token)
        if not device:
            await ws.close(code=1008,reason='Invalid device credentials')
            return
        device_id=device.id
        expected_model=device.model_id
    await ws.accept()
    session=WorkerSession(socket=ws,device_id=device_id,model_id=expected_model,
        context_window=2048,max_output_tokens=256)
    await app.state.registry.attach(session)
    await session.send({'type':'connected','device_id':device_id,'protocol_version':1})
    try:
        while True:
            msg=await ws.receive_json()
            if not isinstance(msg,dict): continue
            typ=msg.get('type')
            if typ=='ready':
                caps=msg.get('capabilities',{})
                if not isinstance(caps,dict): continue
                ctx=caps.get('context_window')
                maximum=caps.get('max_output_tokens')
                model=msg.get('model')
                if (model!=expected_model or type(ctx) is not int or type(maximum) is not int
                    or not 128<=ctx<=32768 or not 1<=maximum<=ctx):
                    await session.send({'type':'error','code':'INVALID_CAPABILITIES'})
                    continue
                session.model_id=model
                session.context_window=ctx
                session.max_output_tokens=maximum
                session.ready=True
                await session.send({'type':'ready_ack','device_id':device_id})
            elif typ=='not_ready':
                session.ready=False
            elif typ=='ping':
                await session.send({'type':'pong'})
            elif typ=='inference_result':
                app.state.registry.resolve(session,msg)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        await app.state.registry.detach(session)

@app.get('/v1/models')
def available_models(authorization:str|None=Header(None),db:Session=Depends(get_db)):
    key=check_api_key(db,authorization)
    device=key.device
    return {'object':'list','data':[{'id':device.model_id,'object':'model','owned_by':'pocketnode',
        'online':device_status(device.id)['ready']} ]}

@app.get('/v1/device/status')
def inference_status(authorization:str|None=Header(None),db:Session=Depends(get_db)):
    key=check_api_key(db,authorization)
    return {'device_id':key.device_id,**device_status(key.device_id)}

@app.post('/v1/chat/completions')
async def completions(req:ChatCompletionRequest, authorization:str|None=Header(None),db:Session=Depends(get_db)):
    key=check_api_key(db,authorization)
    if req.stream:
        raise HTTPException(400,{'code':'STREAMING_NOT_SUPPORTED','message':'Streaming is planned for milestone 2.'})
    session=app.state.registry.get(key.device_id)
    if not session or not session.ready:
        raise HTTPException(503,{'code':'DEVICE_OFFLINE','message':'Open the phone app, load model and start hosting.'})
    if req.model != session.model_id:
        raise HTTPException(400,{'code':'MODEL_MISMATCH','message':f'Loaded model is {session.model_id}'})
    if req.max_tokens>session.max_output_tokens:
        raise HTTPException(422,{'code':'OUTPUT_LIMIT','max_output_tokens':session.max_output_tokens})
    if sum(len(m.content) for m in req.messages)>get_settings().max_input_characters:
        raise HTTPException(413,{'code':'INPUT_TOO_LARGE'})
    # Exact token validation must also happen in Flutter with its model tokenizer.
    request_id='chatcmpl_'+secrets.token_hex(12)
    payload={'type':'inference_request','request_id':request_id,'model':req.model,
         'messages':[m.model_dump() for m in req.messages], 'max_tokens':req.max_tokens,
         'temperature':req.temperature,'top_p':req.top_p}
    started=time.monotonic()
    status='error'; prompt_tokens=None; completion_tokens=None
    try:
        result=await app.state.registry.infer(key.device_id,payload,get_settings().inference_timeout_seconds)
        if result.get('status')!='completed' or not isinstance(result.get('output'),str):
            raise HTTPException(502,{'code':'WORKER_FAILURE','message':str(result.get('error','Worker returned an error'))[:200]})
        usage=result.get('usage') or {}
        prompt_tokens=usage.get('prompt_tokens') if type(usage.get('prompt_tokens')) is int else None
        completion_tokens=usage.get('completion_tokens') if type(usage.get('completion_tokens')) is int else None
        status='completed'
        return {'id':request_id,'object':'chat.completion','created':int(time.time()),'model':req.model,
            'choices':[{'index':0,'message':{'role':'assistant','content':result['output']},
            'finish_reason':result.get('finish_reason','stop')}],
            'usage':{'prompt_tokens':prompt_tokens,'completion_tokens':completion_tokens,
                     'total_tokens':prompt_tokens+completion_tokens if prompt_tokens is not None and completion_tokens is not None else None}}
    except WorkerOffline:
        status='offline'; raise HTTPException(503,{'code':'DEVICE_OFFLINE'})
    except WorkerBusy:
        status='busy'; raise HTTPException(429,{'code':'DEVICE_BUSY'})
    except WorkerTimeout:
        status='timeout'; raise HTTPException(504,{'code':'INFERENCE_TIMEOUT'})
    finally:
        try:
            db.add(models.InferenceRecord(id=request_id, device_id=key.device_id, api_key_id=key.id,
                  model=req.model,status=status,latency_ms=int((time.monotonic()-started)*1000),
                  input_tokens=prompt_tokens,output_tokens=completion_tokens))
            db.commit()
        except Exception:
            db.rollback()

@app.get('/admin/requests', dependencies=[Depends(require_admin)])
def recent_requests(db:Session=Depends(get_db)):
    rows=db.scalars(select(models.InferenceRecord).order_by(desc(models.InferenceRecord.created_at)).limit(50)).all()
    return [{'request_id':r.id,'device_id':r.device_id,'status':r.status,
        'latency_ms':r.latency_ms,'input_tokens':r.input_tokens,'output_tokens':r.output_tokens} for r in rows]
