# Flutter coding agent task — Connect existing local Qwen to PocketNode backend

You are the Flutter/Android engineer. The current application **already downloads and successfully runs a Qwen GGUF model locally**. Do not rewrite model download or inference. Preserve existing working code, model UI, architecture, libraries, and offline playground.

## Objective

Implement the *network worker integration* with the FastAPI gateway in the companion `backend/` project. A developer calls the backend's `/v1/chat/completions`, the backend relays it over a persistent WebSocket to the Flutter app, the existing locally loaded Qwen inference engine generates output, and Flutter sends it back. No cloud model API usage. The phone can remain foregrounded for this milestone.

## Mandatory repository inspection

1. Inspect `pubspec.yaml`, native Android config, model manager, inference service, lifecycle handling, and any controller exposing the loaded engine.
2. Locate the exact method for loading the model, receiving a prompt, streaming output, cancellation, tokenization and obtaining token counts.
3. Read `docs/PROTOCOL.md` in the sibling project. Treat this file as the integration contract.
4. Verify actual dependency APIs before coding. Use `web_socket_channel` (or the project's existing equivalent) and `flutter_secure_storage`, with compatible pinned versions.
5. Preserve the locally working UI and model lifecycle; do not unload model on network disconnect.
6. Implement via typed services and controllers, not socket calls embedded in a widget.

## Initial pairing

The backend operator registers a device by calling `POST /admin/devices` with an admin credential. This returns a **device ID** and one-time `device_token`. For MVP, implement a Pair Device screen or settings sheet that accepts:

- Backend base URL (`http://127.0.0.1:8000` for USB reverse; `http://<laptop-LAN-IP>:8000` for physical Wi-Fi; Android emulator uses `http://10.0.2.2:8000`).
- Device token returned by backend. It looks like `pn_dev_<id>_<secret>`.
- Optional server connectivity test (`GET /health`).

Store device token in Android encrypted secure storage via a supported plugin, not plain SharedPreferences. Server base URL may be stored in ordinary preferences. Validate that URL has expected scheme. Never log device token. Never use public developer API key as the worker credential.

Android network requirements: network permission; for **local debug only** support cleartext traffic (`ws://`/`http://`) via debug-specific network policy. Release networking must use `wss://`/`https://` with proper certificates. Do not weaken release security.

## Required hosting behavior

Add explicit `Start Hosting` and `Stop Hosting` actions. `Start Hosting` must require: model actually loaded, valid device token saved, a configured reachable backend, and the user's consent. If the model is not loaded, show a helpful error instead of advertising ready.

On Start Hosting:
1. Open a WebSocket to `<backend-url>/ws/worker` with header `Authorization: Bearer <device_token>`. For Android native use a WebSocket API that supports custom headers (e.g. `IOWebSocketChannel.connect` or supported `dart:io` WebSocket wrapper); verify precise API for resolved package.
2. Wait for `{ "type": "connected", "device_id": "...", "protocol_version": 1 }`.
3. Verify protocol version; verify that the backend's registered model ID matches the loaded model identifier.
4. Send `ready` including the **actual** runtime context capacity and host-approved maximum output; don't claim 8K if runtime initialized at 4K.
5. Wait for `ready_ack`, then show `Hosting: Online`.
6. Send periodic `{ "type": "ping" }` at a modest interval (e.g. 20–30s); handle `pong` if needed. Avoid indefinite aggressive polling.
7. Reconnect with bounded exponential backoff and jitter after temporary network failures, but only while the user wishes to host and the app is actually able to execute inference. Use the same stored token and device ID. Do not register again automatically. Failed authentication must disable automatic retries and display Re-pair Required.
8. When Stop Hosting is tapped, send `not_ready` if connected, close socket, cancel pending inference if possible, and update UI. Leave downloaded model intact.
9. On explicit model unload, send `not_ready` and safely stop hosting before model teardown.
10. Reopening the app must read persisted URL and device token. Loading the model and tapping Start Hosting should restore the same endpoint and key without any backend re-registration.

## Protocol — full contract

Gateway acknowledges connection:
```json
{"type":"connected","device_id":"<registered-id>","protocol_version":1}
```
Phone advertises capability only when model is loaded:
```json
{"type":"ready","model":"qwen3-0.6b","capabilities":{"context_window":4096,"max_output_tokens":1024}}
```
Gateway acknowledges:
```json
{"type":"ready_ack","device_id":"<registered-id>"}
```
Incoming inference:
```json
{"type":"inference_request","request_id":"chatcmpl_123","model":"qwen3-0.6b","messages":[{"role":"system","content":"You are helpful"},{"role":"user","content":"Hello"}],"max_tokens":256,"temperature":0.7,"top_p":1.0}
```
Successful result:
```json
{"type":"inference_result","request_id":"chatcmpl_123","status":"completed","output":"Hi there","finish_reason":"stop","usage":{"prompt_tokens":12,"completion_tokens":4}}
```
Error result:
```json
{"type":"inference_result","request_id":"chatcmpl_123","status":"error","error":"CONTEXT_EXCEEDED"}
```
Request cancellation from gateway:
```json
{"type":"cancel_request","request_id":"chatcmpl_123"}
```

## Inference implementation details

1. Accept only model IDs that match the actual loaded model. If different, return `MODEL_MISMATCH` error.
2. Convert incoming role-based messages using the inference runtime's **correct Qwen chat template**; preserve system/user/assistant history rather than concatenating blindly.
3. Use the actual model tokenizer to calculate prompt tokens **including applied chat template**.
4. Reject `prompt_tokens + max_tokens > loaded_context_window` with `CONTEXT_EXCEEDED` without crashing the worker.
5. Apply supported `max_tokens`, `temperature`, and `top_p` without silently ignoring inputs. If runtime cannot support an option, implement a deliberate error or document a controlled compatibility decision with the backend developer.
6. Execute using the existing native runtime, not a new cloud request. The model is loaded once and reused between requests.
7. Only process **one inference request at a time**; if a second arrives unexpectedly, return `WORKER_BUSY`.
8. Combine streamed native output into the final response for v1 (the gateway uses non-streaming completions). Do not stream token fragments over the protocol yet.
9. Return true runtime token counts when available. If unavailable use `null`; never fake counts by splitting strings on spaces.
10. Handle user cancellation, inference failure, model unload, socket disconnect and timeouts safely; do not leak model resources.
11. Don't log full prompts or secret tokens by default. Do not persist transmitted prompts locally.
12. Do not add a public HTTP server to the phone, inbound port forwarding or a reverse proxy on the phone. The socket is **outbound from the phone**.

## Suggested code organization

Adapt to the existing codebase instead of duplicating services:

```text
lib/features/hosting/
  data/worker_socket_service.dart
  data/hosting_preferences.dart
  domain/worker_protocol.dart
  application/hosting_controller.dart
  presentation/hosting_settings_screen.dart
```

A hosting controller needs access to a long-lived existing inference engine instance. Be careful with Flutter lifecycle and Riverpod `autoDispose`. **Do not claim background hosting support in this milestone.**

## UI requirements

Minimal Hosting section in current app:
- Status: Not paired / Model not loaded / Connecting / Online / Busy / Offline / Error.
- Editable backend URL.
- Paste-and-save one-time device token.
- `Start Hosting` and `Stop Hosting` buttons.
- Show device ID after successful handshake.
- Show model ID, context window, max output tokens.
- Show last request status, inference time and request count.
- Option to Unpair: ask confirmation, clear locally stored device token and close connection. Warn that server-side revocation is a separate operator action.

Do not display the API developer's secret key in the mobile application; it is managed by the backend/client. The model should still work in the offline playground.

## Integration tests

1. Backend is running on laptop; phone and laptop connect via trusted Wi-Fi or ADB reverse.
2. Paste registered `device_token` into app, load Qwen, tap Start Hosting.
3. `GET /admin/devices/{id}/status` shows `ready: true`.
4. Execute `python client/query_model.py "What is machine learning?"` using the API key.
5. Confirm it is a **real Qwen response**, not mock text.
6. Confirm same device/model can serve repeated sequential requests.
7. Stop Hosting → API returns HTTP 503. Restart Hosting → same API key works.
8. Kill/restart Flutter app, load model and Start Hosting → same registered device and key work.
9. Invalid token fails without creating a new registration.
10. Test model mismatch, excessive output, excessive context, and connection loss during inference.
11. Confirm neither local playground nor model download functionality regressed.

## Delivery expectations

Make real code changes in the Flutter repository, run analyzer/tests/build, and document actual device validation. Return changed files, exact commands, tests run, open issues, and any deviation from the protocol. Never report mock responses as on-device Qwen output. If the backend protocol has a genuine flaw, propose a clear minimal change and synchronize it with backend rather than silently inventing a different contract.
