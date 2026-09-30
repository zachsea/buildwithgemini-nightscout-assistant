"""Minimal FastAPI proxy for a deployed A2A agent (Agent Runtime, agents-cli 1.1.0+).

The browser talks ONLY to this proxy (same origin, no CORS, no GCP creds in the
browser). The proxy authenticates with Application Default Credentials and
forwards chat to the deployed agent over the A2A protocol, returning replies as
structured parts the chat UI knows how to show:

  * {"kind": "text", "text": ...}  -> a normal chat bubble
  * {"kind": "a2ui", "data": ...}  -> one A2UI message (beginRendering /
    surfaceUpdate); static/index.html renders these as a card.

Why A2A: agents-cli 1.1.0 (GA) deploys ADK agents to Agent Runtime as A2A agents
and no longer registers the reasoning-engine operation schema the old
`agent_engines.get(...).stream_query()` path relied on (operation_schemas() comes
back empty). The container serves the A2A protocol over the Agent Engine HTTP
passthrough, so this proxy fetches the agent's card and sends messages with the
a2a-sdk client (the same path `agents-cli run --mode a2a` uses). This works for
both A2A and plain ADK 1.1.0 deployments (the container serves A2A either way).

Run:
  pip install -r requirements.txt
  export AGENT_ENGINE_RESOURCE_NAME="projects/.../locations/.../reasoningEngines/..."
  export AGENT_DIRECTORY="app"   # your agent's app directory (agents-cli-manifest.yaml)
  python main.py                 # -> http://localhost:8080
"""

import asyncio
import os
import re
import uuid

import google.auth
import google.auth.transport.requests
from google.cloud import firestore
import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    FilePart,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TextPart,
    TransportProtocol,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

RESOURCE = os.environ.get(
    "AGENT_ENGINE_RESOURCE_NAME",
    "projects/753495725942/locations/us-central1/reasoningEngines/8741389569947074560",
)
# The agent's app directory (matches agent_directory in agents-cli-manifest.yaml).
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")
# Location is embedded in the resource name: projects/<p>/locations/<loc>/reasoningEngines/<id>.
LOCATION = RESOURCE.split("/locations/")[1].split("/")[0]

# A2A endpoint for an Agent Runtime deployment, via the Agent Engine HTTP
# passthrough. The card lives at the well-known path under this base.
A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)
A2A_CARD_URL = f"{A2A_BASE}/.well-known/agent-card.json"

# The agent tags its A2UI data parts with this mime type.
_A2UI_MIME = "application/json+a2ui"

# One set of ADC credentials, refreshed per request (access tokens expire ~1h).
_creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)


def _auth_headers() -> dict[str, str]:
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


app = FastAPI()


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    # Always return JSON so the browser never receives a plain-text 500 page
    # (which shows up in the chat as "Unexpected token 'I', "Internal S"... is
    # not valid JSON"). Any server-side failure now surfaces as a readable
    # message in the chat bubble instead.
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )


# Reuse ONE A2A context per user so the agent remembers the conversation.
_contexts: dict[str, str] = {}
# Cache the agent card after the first fetch.
_card: AgentCard | None = None


async def _get_card(client: httpx.AsyncClient) -> AgentCard:
    global _card
    if _card is None:
        resp = await client.get(A2A_CARD_URL)
        resp.raise_for_status()
        card = AgentCard(**resp.json())
        # Agent Runtime does not serve a public card URL, so point the client at
        # the passthrough base for message sends.
        card.url = A2A_BASE
        _card = card
    return _card


def _extract_parts(parts: list | None) -> list[dict]:
    """Turn A2A response parts into structured parts for the chat UI.

    Text parts pass through as {"kind": "text"}. A2UI data parts (tagged
    application/json+a2ui) become {"kind": "a2ui", "data": <message>} so the UI
    renders the card; each data part is one A2UI message (beginRendering or
    surfaceUpdate).
    """
    if not parts:
        return []
    out: list[dict] = []
    for p in parts:
        if p is None:
            continue
        root = getattr(p, "root", p)
        if isinstance(root, TextPart) and getattr(root, "text", None):
            out.append({"kind": "text", "text": root.text})
        elif getattr(root, "data", None) is not None:
            data = root.data
            meta = getattr(root, "metadata", None) or {}
            mime = meta.get("mimeType") if isinstance(meta, dict) else None
            # Handle envelope shapes: {"metadata": {"mimeType": "application/json+a2ui"}, "data": {...}}
            if isinstance(data, dict):
                if not mime and "metadata" in data and isinstance(data["metadata"], dict):
                    mime = data["metadata"].get("mimeType")
                if (
                    mime == _A2UI_MIME
                    or any(k in data for k in ("beginRendering", "surfaceUpdate", "dataModelUpdate", "deleteSurface"))
                    or ("data" in data and isinstance(data["data"], dict) and any(k in data["data"] for k in ("beginRendering", "surfaceUpdate", "dataModelUpdate", "deleteSurface")))
                ):
                    inner_data = (
                        data["data"]
                        if ("data" in data and isinstance(data["data"], dict) and any(k in data["data"] for k in ("beginRendering", "surfaceUpdate", "dataModelUpdate", "deleteSurface")))
                        else data
                    )
                    out.append({"kind": "a2ui", "data": inner_data})
                    continue
            if mime == _A2UI_MIME:
                out.append({"kind": "a2ui", "data": data})
            elif isinstance(data, str):
                out.append({"kind": "text", "text": data})
        elif isinstance(root, FilePart):
            uri = getattr(getattr(root, "file", None), "uri", None)
            if uri:
                out.append({"kind": "text", "text": uri})
        elif isinstance(root, dict):
            if "text" in root and root["text"]:
                out.append({"kind": "text", "text": root["text"]})
            elif "data" in root and root["data"]:
                out.append({"kind": "a2ui", "data": root.get("data")})
    return out


def _redact_secrets(obj: any) -> any:
    """Recursively scrub known API tokens and sensitive token patterns from text and JSON."""
    if obj is None:
        return None
    if isinstance(obj, str):
        redacted = re.sub(r'gemini-[a-f0-9]{16}', '[MASKED - CONFIGURED]', obj, flags=re.IGNORECASE)
        redacted = re.sub(r'token[:=\s]+[a-zA-Z0-9_\-]{8,}', 'token: [MASKED - CONFIGURED]', redacted, flags=re.IGNORECASE)
        return redacted
    elif isinstance(obj, dict):
        return {k: _redact_secrets(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_redact_secrets(item) for item in obj]
    return obj


_firestore_client = None


def _get_db():
    global _firestore_client
    if _firestore_client is None:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-c0fc118b7249")
        _firestore_client = firestore.Client(project=project_id)
    return _firestore_client


@app.get("/api/stats")
async def get_stats(user_id: str = "web-user"):
    try:
        db = _get_db()
        doc = db.collection("nightscout_profiles").document(user_id).get()
        if not doc.exists:
            return JSONResponse({"status": "error", "message": f"No Nightscout profile found for {user_id}"})
        profile = doc.to_dict() or {}
        url = profile.get("nightscout_url", "").rstrip("/")
        token = profile.get("access_token", "")
        if not url:
            return JSONResponse({"status": "error", "message": "Nightscout URL not configured in profile"})

        target_low = float(profile.get("target_low", 70))
        target_high = float(profile.get("target_high", 180))

        entries_url = f"{url}/api/v1/entries.json?count=288"
        treatments_url = f"{url}/api/v1/treatments.json?count=100"
        if token:
            entries_url += f"&token={token}"
            treatments_url += f"&token={token}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resps = await asyncio.gather(
                client.get(entries_url),
                client.get(treatments_url),
                return_exceptions=True,
            )

        entries_resp, treats_resp = resps[0], resps[1]
        entries_data = (
            entries_resp.json()
            if not isinstance(entries_resp, Exception) and getattr(entries_resp, "status_code", 0) == 200
            else []
        )
        treats_data = (
            treats_resp.json()
            if not isinstance(treats_resp, Exception) and getattr(treats_resp, "status_code", 0) == 200
            else []
        )

        valid_entries = [e for e in entries_data if isinstance(e.get("sgv"), (int, float))]
        arrow_map = {
            "DoubleUp": "⇈",
            "SingleUp": "↑",
            "FortyFiveUp": "↗",
            "Flat": "→",
            "FortyFiveDown": "↘",
            "SingleDown": "↓",
            "DoubleDown": "⇊",
        }

        cgm_info = {
            "sgv": "--",
            "direction": "None",
            "arrow": "--",
            "delta": "0",
            "time": "--:-- UTC",
            "status_color": "normal",
        }
        analytics_info = {
            "avg": "--",
            "min": "--",
            "max": "--",
            "tir_pct": 0,
            "above_pct": 0,
            "below_pct": 0,
            "target_low": int(target_low),
            "target_high": int(target_high),
            "readings_count": 0,
        }
        timeline = []
        graph_points = []

        if valid_entries:
            latest = valid_entries[0]
            latest_sgv = int(latest["sgv"])
            latest_dir = latest.get("direction", "Flat")
            arrow = arrow_map.get(latest_dir, "→")
            latest_time = latest.get("dateString", "")
            t_fmt = latest_time[11:16] + " UTC" if len(latest_time) >= 16 else latest_time

            delta_val = 0
            delta_str = "0"
            if len(valid_entries) >= 2:
                prev_sgv = int(valid_entries[1]["sgv"])
                delta_val = latest_sgv - prev_sgv
                delta_str = f"+{delta_val}" if delta_val > 0 else str(delta_val)

            status_color = "normal"
            if latest_sgv < target_low:
                status_color = "danger" if latest_sgv < 55 else "warning"
            elif latest_sgv > target_high:
                status_color = "danger" if latest_sgv > 250 else "warning"

            cgm_info = {
                "sgv": latest_sgv,
                "direction": latest_dir,
                "arrow": arrow,
                "delta": delta_str,
                "time": t_fmt,
                "status_color": status_color,
            }

            all_sgvs = [int(e["sgv"]) for e in valid_entries]
            avg_sgv = round(sum(all_sgvs) / len(all_sgvs))
            min_sgv = min(all_sgvs)
            max_sgv = max(all_sgvs)
            in_range = sum(1 for s in all_sgvs if target_low <= s <= target_high)
            tir_pct = round((in_range / len(all_sgvs)) * 100)
            above_pct = round((sum(1 for s in all_sgvs if s > target_high) / len(all_sgvs)) * 100)
            below_pct = round((sum(1 for s in all_sgvs if s < target_low) / len(all_sgvs)) * 100)

            analytics_info = {
                "avg": avg_sgv,
                "min": min_sgv,
                "max": max_sgv,
                "tir_pct": tir_pct,
                "above_pct": above_pct,
                "below_pct": below_pct,
                "target_low": int(target_low),
                "target_high": int(target_high),
                "readings_count": len(all_sgvs),
            }

            # Recent 12 readings for timeline pill stream
            for e in valid_entries[:12]:
                dt = e.get("dateString", "")
                d_fmt = dt[11:16] if len(dt) >= 16 else dt
                d_dir = e.get("direction", "Flat")
                timeline.append({
                    "time": d_fmt,
                    "sgv": int(e["sgv"]),
                    "direction": d_dir,
                    "arrow": arrow_map.get(d_dir, "→"),
                })

            # Chronological (oldest to newest) 24h graph points
            for e in reversed(valid_entries):
                sgv_pt = int(e["sgv"])
                dt = e.get("dateString", "")
                pt_time = dt[11:16] if len(dt) >= 16 else dt
                pt_dir = e.get("direction", "Flat")
                pt_color = "normal"
                if sgv_pt < target_low:
                    pt_color = "danger" if sgv_pt < 55 else "warning"
                elif sgv_pt > target_high:
                    pt_color = "danger" if sgv_pt > 250 else "warning"
                graph_points.append({
                    "time": pt_time,
                    "sgv": sgv_pt,
                    "direction": pt_dir,
                    "arrow": arrow_map.get(pt_dir, "→"),
                    "color": pt_color,
                    "dateString": dt,
                })

        total_bolus = 0.0
        total_carbs = 0.0
        basal_rate = 0.40
        doses_24h = []
        recent_treatments = []

        for t in treats_data:
            ins = t.get("insulin")
            crb = t.get("carbs")
            t_type = t.get("eventType", "Treatment")
            created_at = t.get("created_at") or t.get("timestamp") or ""
            time_sub = created_at[11:16] if len(created_at) >= 16 else created_at
            notes = t.get("notes") or t.get("reason") or ""

            if "rate" in t and isinstance(t["rate"], (int, float)):
                basal_rate = float(t["rate"])
            elif "absolute" in t and isinstance(t["absolute"], (int, float)):
                basal_rate = float(t["absolute"])

            ins_val = float(ins) if ins is not None and isinstance(ins, (int, float)) and ins > 0 else 0.0
            crb_val = float(crb) if crb is not None and isinstance(crb, (int, float)) and crb > 0 else 0.0

            if ins_val > 0 or crb_val > 0:
                total_bolus += ins_val
                total_carbs += crb_val
                desc = []
                if ins_val > 0:
                    desc.append(f"{ins_val:.2f} U" if (ins_val * 100) % 10 else f"{ins_val:.1f} U")
                if crb_val > 0:
                    desc.append(f"{int(crb_val)}g carbs")

                dose_item = {
                    "time": time_sub,
                    "created_at": created_at,
                    "type": t_type,
                    "insulin": round(ins_val, 2),
                    "carbs": round(crb_val, 1),
                    "notes": notes,
                    "summary": " • ".join(desc),
                }
                doses_24h.append(dose_item)
                if len(recent_treatments) < 6:
                    recent_treatments.append(dose_item)

        est_basal = round(basal_rate * 24, 2)
        total_daily_dose = round(total_bolus + est_basal, 2)

        treatments_summary_24h = {
            "total_bolus": round(total_bolus, 2),
            "total_carbs": round(total_carbs, 1),
            "basal_rate": basal_rate,
            "est_basal_24h": est_basal,
            "tdd": total_daily_dose,
            "doses": doses_24h,
            "dose_count": len(doses_24h),
        }

        payload = {
            "status": "ok",
            "nightscout_url": url,
            "cgm": cgm_info,
            "analytics": analytics_info,
            "graph_24h": graph_points,
            "treatments_24h": treatments_summary_24h,
            "treatments": {
                "total_bolus": round(total_bolus, 2),
                "basal_rate": basal_rate,
                "total_carbs": round(total_carbs, 1),
            },
            "timeline": timeline,
            "recent_treatments": recent_treatments,
        }
        return JSONResponse(_redact_secrets(payload))

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "")
    user_id = body.get("user_id") or "web-user"
    parts: list[dict] = []

    async with httpx.AsyncClient(headers=_auth_headers(), timeout=120) as client:
        card = await _get_card(client)
        factory = ClientFactory(
            ClientConfig(
                supported_transports=[
                    TransportProtocol.jsonrpc,
                    TransportProtocol.http_json,
                ],
                httpx_client=client,
            )
        )
        a2a_client = factory.create(card)

        formatted_message = message
        if user_id and f"[User: {user_id}]" not in message:
            formatted_message = f"[User: {user_id}] {message}"

        msg = Message(
            message_id=str(uuid.uuid4()),
            role=Role.user,
            parts=[Part(root=TextPart(text=formatted_message))],
            context_id=_contexts.get(user_id),
        )

        last_task = None
        got_artifact_update = False
        async for event in a2a_client.send_message(msg):
            if not isinstance(event, tuple):
                continue
            task, update = event
            if task is not None:
                last_task = task
                if getattr(task, "context_id", None):
                    _contexts[user_id] = task.context_id
            if isinstance(update, TaskArtifactUpdateEvent):
                artifact = getattr(update, "artifact", None)
                if artifact and getattr(artifact, "parts", None):
                    extracted = _extract_parts(artifact.parts)
                    if extracted:
                        got_artifact_update = True
                        parts.extend(extracted)

        # Non-streaming fallback: pull parts from the final task's artifacts or history.
        if not got_artifact_update and last_task is not None:
            for artifact in getattr(last_task, "artifacts", None) or []:
                if getattr(artifact, "parts", None):
                    extracted = _extract_parts(artifact.parts)
                    if extracted:
                        parts.extend(extracted)
            if not parts:
                for hist_msg in reversed(getattr(last_task, "history", None) or []):
                    if getattr(hist_msg, "role", None) in (Role.agent, "agent"):
                        extracted = _extract_parts(getattr(hist_msg, "parts", None))
                        if extracted:
                            parts.extend(extracted)
                            break

    if not parts:
        # The turn produced no text or UI (e.g. the agent only ran tools, or a
        # tool stalled). Be honest rather than silent.
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]
    return JSONResponse({"parts": _redact_secrets(parts)})


# Serve the chat UI (keep this mount last so /chat wins).
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
