# Danex Global Hybrid RAG Service

> Hybrydowy backend RAG z wyszukiwaniem semantycznym i odpowiedziami opartymi o SQL.

![Danex RAG overview](C:/Users/syfsy/projekty/danex-rag-service/docs/assets/console-overview.png)

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=for-the-badge&logo=langchain)](https://langchain.com/)
[![Gemini](https://img.shields.io/badge/Google_Gemini-8E75B2?style=for-the-badge&logo=googlegemini)](https://deepmind.google/technologies/gemini/)
[![CI](https://github.com/danieloza/danex-rag-service/actions/workflows/ci.yml/badge.svg)](https://github.com/danieloza/danex-rag-service/actions/workflows/ci.yml)

## Product Thesis

Wiekszosc prostych demo RAG konczy sie na:

- wrzuceniu dokumentu
- odpaleniu embeddings
- i wygenerowaniu odpowiedzi bez jasnego sygnalu, skad ona pochodzi

Danex RAG idzie krok dalej:

- laczy retrieval dokumentowy z odpowiedziami opartymi o SQL
- pokazuje route (`sql`, `vector`, `hybrid`, `none`)
- zwraca cytaty i score zrodel
- trzyma historie pytan i ingestu
- pozwala zarzadzac knowledge base z poziomu UI

To repo ma pokazywac praktyczny backend RAG, a nie tylko jednorazowy eksperyment z LangChain.

## Why This Matters In Production

W realnym systemie AI sama odpowiedz nie wystarcza.

- operator musi wiedziec, czy odpowiedz przyszla z danych operacyjnych czy z dokumentow
- zespol musi widziec, jakie pliki sa aktualnie w knowledge base
- ingestion nie moze byc czarna skrzynka
- latency i score zrodel powinny byc widoczne
- query history i evaluation summary pomagaja zobaczyc, jak system zachowuje sie w praktyce

## Kluczowe cechy techniczne

- hybrydowy pipeline laczacy FAISS semantic search z Text-to-SQL nad bazami operacyjnymi
- warstwa API oparta o FastAPI do inference i generowania raportow
- lokalne embeddingi z HuggingFace `sentence-transformers/all-MiniLM-L6-v2`
- generowanie zapytan SQL i synteza odpowiedzi wspierane przez Gemini
- walidacja requestow w Pydantic i jawne kontrakty API
- endpoint health i podstawowe logowanie do diagnostyki runtime
- upload + rebuild dla ingestion
- query history, ingestion history i evaluation summary
- source citations z podobienstwem i preview

## Stack technologiczny

- Inference: Google Gemini 2.0 Flash
- Frameworks: FastAPI, LangChain, Pydantic
- Vector Store: FAISS
- Data Sources: SQLite (`salonos.db`, `danex.db`)
- Embeddings: HuggingFace `all-MiniLM-L6-v2`

## Powierzchnia API

- `POST /api/v1/ask`
- `POST /api/v1/query`
- `POST /api/v1/ingest/upload`
- `POST /api/v1/ingest/rebuild`
- `POST /api/v1/report/pdf`
- `GET /api/v1/history/queries`
- `GET /api/v1/ingest/history`
- `GET /api/v1/evals/summary`
- `DELETE /api/v1/ingest/files/{filename}`
- `GET /api/v1/report/download/{filename}`
- `GET /health`

## Demo Walkthrough

1. Wrzuc pliki do knowledge base przez `Upload + rebuild`.
2. Zadaj pytanie przez UI.
3. Sprawdz, czy system poszedl przez `sql`, `vector` czy `hybrid`.
4. Rozwin cytaty i zobacz preview zrodla oraz score.
5. Sprawdz query history i evaluation summary.
6. Usun plik z knowledge base i odpal rebuild, zeby zobaczyc jak zmienia sie stan produktu.

## Instalacja i uruchomienie

Sklonuj repozytorium:

```bash
git clone https://github.com/danieloza/danex-rag-service.git
cd danex-rag-service
```

Zainstaluj zaleznosci:

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

Skonfiguruj srodowisko:

```bash
cp .env.example .env
```

Przed uruchomieniem ustaw `GOOGLE_API_KEY`. Opcjonalne sciezki do baz mozesz nadpisac przez `SALONOS_DB_PATH` i `DANEX_DB_PATH`.

Uruchom lokalnie:

```bash
uvicorn main:app --host 127.0.0.1 --port 8002 --reload
```

Po uruchomieniu wejdz na `http://127.0.0.1:8002/` aby otworzyc prosta konsole RAG.

Uruchom szybki smoke test:

```bash
python -m pytest -q tests
```

## Ingestion i FAISS

Budowanie lokalnego indeksu FAISS:

```bash
python ingest.py
```

`ingest.py` korzysta z MarkItDown do konwersji plikow na Markdown
(PDF, DOCX, PPTX, XLSX, HTML, CSV, JSON itd.). Jesli MarkItDown nie jest
zainstalowany, pliki nietekstowe zostana pominiete z ostrzezeniem.

## Nowe endpointy UX

- `POST /api/v1/ingest/upload` (multipart) - upload plikow do knowledge_base + opcjonalny rebuild
- `POST /api/v1/ingest/rebuild` - rebuild indeksu FAISS w tle
- `GET /api/v1/ingest/history` - historia ingestu i lista aktualnych plikow
- `DELETE /api/v1/ingest/files/{filename}` - usuniecie pliku i opcjonalny rebuild
- `GET /api/v1/history/queries` - historia ostatnich pytan
- `GET /api/v1/debug/index` - status indeksu + meta ingestu
- `GET /api/v1/debug/db` - status baz SQLite
- `GET /api/v1/evals/summary` - prosta warstwa oceny: liczba zapytan, route breakdown, sredni latency, sredni top score

Odpowiedz `/api/v1/ask` zwraca dodatkowo:

- `meta.route` (`sql`, `vector`, `hybrid`, `none`)
- `citations` z fragmentami zrodel vectorowych
- `citations[].score` (znormalizowany score podobienstwa)

UI pokazuje teraz:

- query history
- ingestion history
- source preview przez rozwiniecie cytatu
- knowledge files z opcja delete + rebuild
- evaluation summary dla ostatnich zapytan

## Proof Assets

- console overview: [docs/assets/console-overview.png](/C:/Users/syfsy/projekty/danex-rag-service/docs/assets/console-overview.png)
  pokazuje glowny ekran z pytaniem, odpowiedzia, route i citations
- ingestion workflow: [docs/assets/ingestion-workflow.png](/C:/Users/syfsy/projekty/danex-rag-service/docs/assets/ingestion-workflow.png)
  pokazuje knowledge files, upload/rebuild i ingestion history
- query + eval history: [docs/assets/query-eval-history.png](/C:/Users/syfsy/projekty/danex-rag-service/docs/assets/query-eval-history.png)
  pokazuje historie pytan i warstwe prostego monitoringu jakosci

Uwagi:

- `GET /health` i lokalny smoke test nie wymagaja aktywnego requestu do Gemini
- pelne odpowiedzi hybrydowe wymagaja `GOOGLE_API_KEY` oraz dostepu do docelowych zrodel danych SQLite

## Uwagi architektoniczne

- kontekst wektorowy jest ladowany z lokalnego katalogu `faiss_index`
- odpowiedzi SQL sa generowane na bazach SQLite SalonOS i Danex
- raporty PDF sa generowane przez `pdf_generator.py`
- serwis preferuje lokalny `.env`, a w drugiej kolejnosci korzysta ze wspoldzielonego `.env.global`
- projekt jest pomyslany jako warstwa AI inference dzialajaca obok backendowego stosu Danex

## Jak opowiedziec ten projekt na rozmowie

Danex RAG to hybrydowy backend RAG w FastAPI, ktory laczy semantic retrieval z odpowiedziami opartymi o SQL nad danymi operacyjnymi. Celem bylo zbudowanie praktyczniejszego systemu niz prosty chatbot dokumentowy: z ingestion layer, route transparency, source scoring, query history i prostym evaluation summary.

## Dodatkowa dokumentacja

- Architektura: [docs/ARCHITECTURE.md](/C:/Users/syfsy/projekty/danex-rag-service/docs/ARCHITECTURE.md)
- Case study: [docs/CASE_STUDY.md](/C:/Users/syfsy/projekty/danex-rag-service/docs/CASE_STUDY.md)
- Krotka wersja pod rozmowe: [docs/README_SHORT_PL.md](/C:/Users/syfsy/projekty/danex-rag-service/docs/README_SHORT_PL.md)
