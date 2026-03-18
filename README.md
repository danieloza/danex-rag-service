# Danex Global Hybrid RAG Service

> Advanced retrieval-augmented generation engine with semantic search and SQL-backed answers.

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=for-the-badge&logo=langchain)](https://langchain.com/)
[![Gemini](https://img.shields.io/badge/Google_Gemini-8E75B2?style=for-the-badge&logo=googlegemini)](https://deepmind.google/technologies/gemini/)
[![CI](https://github.com/danieloza/danex-rag-service/actions/workflows/ci.yml/badge.svg)](https://github.com/danieloza/danex-rag-service/actions/workflows/ci.yml)

## Overview

Danex RAG is an inference service designed to bridge unstructured documentation with structured operational data. It uses a hybrid retrieval flow that routes questions between vector-based semantic search and SQL query synthesis for deterministic answers.

## Key Engineering Features

- Hybrid retrieval pipeline combining FAISS semantic search with Text-to-SQL over operational databases
- FastAPI-based service layer for low-latency API inference and report generation
- Local-first embeddings using HuggingFace `sentence-transformers/all-MiniLM-L6-v2`
- Gemini-powered SQL query generation and answer synthesis
- Pydantic request validation and explicit API contracts for stable integration
- Health endpoint and logging hooks for runtime diagnostics

## Tech Stack

- Inference: Google Gemini 2.0 Flash
- Frameworks: FastAPI, LangChain, Pydantic
- Vector Store: FAISS
- Data Sources: SQLite (`salonos.db`, `danex.db`)
- Embeddings: HuggingFace `all-MiniLM-L6-v2`

## API Surface

- `POST /api/v1/ask`
- `POST /api/v1/query`
- `POST /api/v1/report/pdf`
- `GET /api/v1/report/download/{filename}`
- `GET /health`

## Installation and Setup

Clone the repository:

```bash
git clone https://github.com/danieloza/danex-rag-service.git
cd danex-rag-service
```

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Configure environment:

```bash
cp .env.example .env
```

Set `GOOGLE_API_KEY` before starting the service. Optional database paths can be overridden through `SALONOS_DB_PATH` and `DANEX_DB_PATH`.

Run locally:

```bash
uvicorn main:app --host 127.0.0.1 --port 8002 --reload
```

Run a quick smoke check:

```bash
python -m pytest -q
```

## Architecture Notes

- Vector context is loaded from the local `faiss_index` directory
- SQL answers are generated against SalonOS and Danex SQLite databases
- PDF reports are generated through `pdf_generator.py`
- The service prefers a local `.env` and falls back to the shared workspace `.env.global`
- The service is intended to sit alongside the Danex backend stack as an AI inference layer
