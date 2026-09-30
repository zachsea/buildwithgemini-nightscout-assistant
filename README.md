# Nightscout Assistant

A conversational health assistant built on **Google Agent Development Kit (ADK)** and **Vertex AI Agent Runtime**, connecting to [Nightscout](https://nightscout.github.io/) to help individuals with diabetes track and understand their glucose dynamics and insulin treatments.

---

## Features

- **Real-time CGM Glucose**: Fetches immediate blood glucose levels with trend directions (`→`, `↗`, `↑`, `↘`, `↓`) and rate of change.
- **Historical Glucose Trends**: Computes 2-hour window analytics including average glucose, window extremes (min/max), time-in-range (TIR %) against personalized targets, and chronological readings timeline.
- **Insulin & Treatment Tracking**: Inspects recent bolus deliveries (standard, combo/extended), active temporary basal rates, and carbohydrate intake logs.
- **Rich A2UI Surfaces**: Natively renders structured, card-based dashboards using the A2UI v0.8 specification directly in chat.
- **Security & Privacy First**: Nightscout tokens and credentials are securely stored in Google Cloud Firestore, masked from the LLM, and scrubbed at the API proxy layer to prevent credential leaks.

---

## Project Structure

```
nightscout-assistant/
├── app/
│   ├── agent.py               # Main ADK agent with system prompt & A2UI layout
│   ├── nightscout_tools.py    # Nightscout API & Firestore profile integration tools
│   ├── a2ui_utils.py          # A2UI callback transformer for A2A parts
│   └── __init__.py
├── frontend/
│   ├── main.py                # FastAPI proxy connecting browser to Agent Runtime via A2A
│   ├── static/index.html      # Responsive chat interface with native A2UI renderer
│   └── requirements.txt
├── agents-cli-manifest.yaml   # Agent deployment manifest
├── deployment_metadata.json   # Deployment resource configuration
├── pyproject.toml             # Python dependencies (managed via uv)
└── README.md
```

---

## Tools & Services

| Tool / Capability | Implementation Status | Description |
|---|---|---|
| `fetch_current_glucose` | ✅ Live | Fetches real-time sensor glucose reading and direction arrow. |
| `fetch_glucose_trends` | ✅ Live | Analyzes 2-hour historical readings, TIR %, average, min/max, and timeline. |
| `fetch_recent_treatments` | ✅ Live | Retrieves bolus deliveries, temp basals, and logged carbs from Nightscout. |
| `get_nightscout_profile` | ✅ Live | Retrieves target glucose ranges and masked configuration from Firestore. |
| `update_nightscout_profile` | ✅ Live | Saves target range updates and Nightscout credentials to Firestore. |
| A2UI Renderer | ✅ Live | Renders rich cards (Metrics, Timelines, Dividers, Badges) in the chat UI. |

---

## Running Locally

### 1. Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [Google Cloud SDK](https://cloud.google.com/sdk) authenticated with `gcloud auth application-default login`

### 2. Run the Agent Locally

Install dependencies:
```bash
uv sync
```

Launch the ADK playground:
```bash
uv run adk web app
```

### 3. Run the Frontend Proxy

```bash
cd frontend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export AGENT_ENGINE_RESOURCE_NAME="<your-reasoning-engine-resource-name>"
export AGENT_DIRECTORY="app"
export PORT=8080
python main.py
```
Open `http://localhost:8080` in your browser.

---

## Deployment

Deploy to Vertex AI Agent Runtime with `agents-cli`:
```bash
agents-cli deploy --project <your-gcp-project-id> --region <region>
```
