# Asili Operations Team

> AI-powered operations team for micro-sellers — a multi-agent system built with Google ADK for the Google Agents Challenge (Track 1).

## Overview

Asili Operations Team demonstrates how specialized AI agents can collaborate to handle customer inquiries for small e-commerce sellers. The system routes incoming messages through an operations manager that delegates to specialist agents for catalog lookup and pricing, ensuring responses are grounded in real data and margin-safe.

### The Problem

A single LLM prompted with a customer question will often:
- **Hallucinate inventory** ("We have 32 tins in stock" when there are only 6)
- **Quote unsafe prices** ($24 for a bundle that costs $14.80 to fulfill — below margin floor)

### The Solution

A multi-agent operations team where:
- **Operations Manager** routes and orchestrates
- **Messaging Agent** grounds responses in the real catalog via RAG
- **Pricing Agent** uses deterministic tools to ensure margin safety

Every response passes through a human approval gate before sending.

## Architecture

```
Customer Message
       │
       ▼
┌──────────────────┐
│ Operations Mgr   │ ◄── Root LlmAgent
│ (orchestrator)   │
└────────┬─────────┘
         │ delegates
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────┐
│Messaging│ │Pricing │
│ Agent  │ │ Agent  │
└────┬───┘ └────┬───┘
     │          │
     ▼          ▼
┌────────┐ ┌────────────────┐
│Catalog │ │compute_bundle_ │
│Search  │ │price (determ.) │
└────────┘ └────────────────┘
         │
         ▼
┌──────────────────┐
│ Human Approval   │
│ Gate             │
└────────┬─────────┘
         │ approved
         ▼
    Send via Telegram
```

## Quick Start

### Prerequisites

- Python 3.11+
- Google Cloud project with Vertex AI enabled
- Telegram Bot Token (for channel integration)

### Installation

```bash
# Clone the repository
git clone https://github.com/Jeremiah-Sakuda/asili-agents.git
cd asili-agents

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Edit .env with your credentials
```

### Configuration

Set the following environment variables in `.env`:

```env
# Google Cloud
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1

# Google Gemini API Key (for local development)
# Get one at: https://aistudio.google.com/app/apikey
GOOGLE_API_KEY=your-api-key

# Vertex AI Search (optional, for catalog grounding in production)
VERTEX_SEARCH_DATASTORE_ID=your-datastore-id

# Telegram (optional, for channel integration)
TELEGRAM_BOT_TOKEN=your-bot-token

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/asili_agents
```

### Running Locally

```bash
# Start the API server
uvicorn asili_agents.api.main:app --reload

# Run the agent demo
python -m asili_agents.demo
```

### Running Tests

```bash
pytest
```

## Project Structure

```
asili-agents/
├── src/asili_agents/
│   ├── agents/           # Agent definitions
│   │   ├── operations_manager.py
│   │   ├── messaging.py
│   │   ├── pricing.py
│   │   └── baseline.py   # Monolithic baseline for comparison
│   ├── tools/            # ADK FunctionTools
│   │   ├── catalog.py
│   │   ├── pricing.py
│   │   └── channel.py
│   ├── grounding/        # Vertex AI Search / RAG
│   ├── data/             # Database models & seed data
│   └── api/              # FastAPI endpoints
├── frontend/             # React Operations Console
├── tests/
├── scripts/              # Deployment & utility scripts
└── .github/workflows/    # CI/CD
```

## Demo Scenario

The demo features **Mahaba Tea Co.**, a Kenyan tea seller:

| Product | Price | Cost | Margin | Stock |
|---------|-------|------|--------|-------|
| Purple Tea (50g tin) | $18.00 | $7.40 | 59% | 6 tins |
| Green Tea (50g tin) | $15.00 | $6.20 | 59% | 12 tins |
| Black Tea (50g tin) | $14.00 | $5.80 | 59% | 8 tins |

**Policy:** Minimum margin floor of 45%

### Sample Interaction

**Customer:** "Do you have the purple tea in stock? Can you do a bundle?"

**Baseline (single model):** "Yes! We have 32 tins... bundle for $24" ❌
- Hallucinated stock (actual: 6)
- Below margin floor (38% vs 45% minimum)

**Operations Team:** "Yes — Purple Tea is in stock (6 tins left). I can do a 2-tin bundle for $34, shipped together." ✓
- Grounded on real catalog
- Margin safe (56% > 45% floor)

## Deployment

### Cloud Run

```bash
# Deploy to Google Cloud Run
./scripts/deploy.sh
```

The deploy script will:
1. Enable required GCP APIs (Cloud Run, Vertex AI, Artifact Registry)
2. Build and push the Docker image
3. Deploy to Cloud Run with auto-scaling

### Environment Setup

The system requires a Google Cloud project with:
- Vertex AI API enabled
- Cloud Run API enabled
- (Optional) Vertex AI Search configured with catalog data
- Service account with appropriate permissions

### Running Integration Tests

To run tests that execute real agent workflows:

```bash
GOOGLE_API_KEY=your-api-key pytest tests/test_agents.py -v
```

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

Built for the [Google for Startups Agents Challenge](https://googleforstartups.com/) using:
- [Google ADK](https://cloud.google.com/vertex-ai/docs/agents/adk)
- [Vertex AI](https://cloud.google.com/vertex-ai)
- [Gemini](https://cloud.google.com/vertex-ai/docs/generative-ai/model-reference/gemini)
