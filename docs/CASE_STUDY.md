# Case Study

## Problem

Teams often have two separate sources of truth:

- documentation, policies, and unstructured notes
- operational data sitting in relational databases

Pure semantic search is weak for precise business questions. Pure SQL is weak for procedural or policy questions.

## Solution

`danex-rag-service` combines both modes in one API:

- semantic retrieval over a local FAISS index for documentation-backed context
- SQL synthesis against SQLite business data for deterministic answers
- a single FastAPI surface for applications that need both

## Why It Matters

This is a compact example of a practical AI backend, not just a model wrapper.

It shows how to:

- decide when vector retrieval is useful
- decide when structured data access is required
- keep embeddings local for lower cost and latency
- expose the combined flow through a stable API

## Engineering Signals

- FastAPI service design
- local-first embedding pipeline
- hybrid retrieval architecture
- report generation endpoint
- smoke-level CI and API tests

## What I Would Improve Next

- stricter SQL validation and allowlists
- stronger evaluation datasets for answer quality
- retrieval and SQL telemetry
- better separation between inference, retrieval, and reporting layers
