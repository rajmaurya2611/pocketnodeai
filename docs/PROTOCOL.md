# PocketNode worker wire protocol v1

Transport: one outbound authenticated WebSocket from phone to `/ws/worker`. Worker supplies `Authorization: Bearer pn_dev_...` as a request **header**. This device credential is separate from the developer API key. **Never place secrets in query parameters.** For production use **WSS/TLS**. Local `ws://` is only for a trusted test network or ADB USB reverse connection.

JSON envelopes:

**Gateway → Worker on successful connection**
```json
{"type":"connected","device_id":"<registered-id>","protocol_version":1}
```

**Worker → Gateway once model is actually loaded and ready**
```json
{"type":"ready","model":"qwen3-0.6b","capabilities":{"context_window":4096,"max_output_tokens":1024}}
```

**Gateway → Worker acknowledgement**
```json
{"type":"ready_ack","device_id":"<registered-id>"}
```

**Gateway → Worker inference request**
```json
{"type":"inference_request","request_id":"chatcmpl_...","model":"qwen3-0.6b","messages":[{"role":"user","content":"Hello"}],"max_tokens":256,"temperature":0.7,"top_p":1.0}
```

**Worker → Gateway inference completion**
```json
{"type":"inference_result","request_id":"chatcmpl_...","status":"completed","output":"Hello from Qwen","finish_reason":"stop","usage":{"prompt_tokens":5,"completion_tokens":7}}
```

**Worker → Gateway inference failure**
```json
{"type":"inference_result","request_id":"chatcmpl_...","status":"error","error":"CONTEXT_EXCEEDED"}
```

**Worker → Gateway on explicit model unload or hosting stop**
```json
{"type":"not_ready"}
```

**Worker → Gateway optional heartbeat**
```json
{"type":"ping"}
```
Response: `{"type":"pong"}`.

**Gateway → Worker cancellation when request timed out**
```json
{"type":"cancel_request","request_id":"chatcmpl_..."}
```

Rules: One in-flight inference per device. Correlate responses strictly by `request_id`. Worker must tokenize using the actual model tokenizer and reject `prompt_tokens + max_tokens > context_window`, including its chat template. Never send fake token usage; `null` is acceptable when unavailable. The worker must not send `ready` until the real engine has loaded. On reconnect the same persisted `device_token` is reused and a new live WebSocket session is created. If the gateway says credentials invalid, **do not** automatically register a new device; require explicit re-pairing.

Current scope: Non-streaming chat completions only. Future streaming should use an explicit new version of this protocol, not ad hoc partial `inference_result` messages. Requests may fail with HTTP 401, 400, 413, 422, 429, 502, 503 or 504. The server currently tracks connections in a single Python process and is not multi-worker safe.
