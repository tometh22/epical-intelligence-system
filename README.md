# Epical Intelligence System

Multi-agent automation platform for social & consumer intelligence.

## Quick Start

### 1. Set up environment

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 2. Install Python dependencies

```bash
pip install -r agents/requirements.txt
```

### 3. Start the API server

```bash
cd /Users/tomi/epical-intelligence-system
python -m uvicorn agents.api_server:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Start the dashboard

```bash
cd dashboard
npm install
npm run dev
```

Dashboard runs at http://localhost:3000, API at http://localhost:8000.

### 5. Run Report Builder via CLI (alternative to dashboard)

```bash
python -m agents.report_builder.main \
  --input inputs/your_export.csv \
  --client "ClientName" \
  --period "Marzo 2026"
```

Outputs go to `outputs/report-builder/`.

## Project Structure

```
/agents
  /report-builder    — Agent 1: YouScan data → intelligence report (.docx)
  /prospecting       — Agent 2: Contact enrichment & outreach (coming soon)
  /content-authority  — Agent 3: Thought leadership content (coming soon)
  /monitor           — Agent 4: Real-time alert monitoring (coming soon)
  /shared            — Shared utilities (Claude client, logger, storage)
  api_server.py      — FastAPI server
/dashboard           — Next.js web interface
/inputs              — Drop input files here
/outputs             — Agent outputs organized by agent and date
/config              — Client configurations and column mappings
/logs                — Agent log files
```

## Column Mapping

The Report Builder auto-detects common column names from YouScan exports. To configure custom mappings for a client, create a JSON file in `config/column_mappings/{client_name}.json`:

```json
{
  "date": "Published",
  "text": "Content",
  "sentiment": "Sentiment",
  "source": "Platform",
  "author": "Author",
  "topic": "Category"
}
```

## API Endpoints

- `GET /health` — Health check
- `POST /api/agents/report-builder/run` — Upload file and run report builder
- `GET /api/agents/report-builder/status` — Get agent status
- `GET /api/agents/report-builder/outputs` — List output files
- `GET /api/agents/report-builder/outputs/{filename}` — Download output file
- `GET /api/logs/{agent_name}` — Get agent logs
