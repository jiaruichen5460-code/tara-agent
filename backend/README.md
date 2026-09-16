# Tara-Agent backend

The backend keeps HTTP transport, deterministic data access, and domain contracts separate.
Source TSV files are immutable inputs; runtime code reads only validated Parquet artifacts.

```text
src/tara_agent/
├── api/          FastAPI application and HTTP schemas/routes
├── analysis/     transport-independent deterministic query services
├── data/         source validation, preprocessing, manifest, and processed-data access
├── domain/       transport-independent shared contracts
├── mcp/          thin MCP server and tool adapters
└── config.py     environment-backed configuration
```

## Preprocess data

Run the reproducible preprocessing pipeline through the project entrypoint:

```powershell
uv run tara-data
```

Use `--force` to rebuild and verify that Parquet checksums are reproducible:

```powershell
uv run tara-data --force
```

Outputs are atomically published below `data/processed/`:

```text
data/processed/
├── manifest.json
└── generation-<fingerprint>/
    ├── context.parquet
    ├── v4_asv_metadata.parquet
    ├── v4_abundance.parquet
    ├── v9_asv_metadata.parquet
    ├── v9_abundance.parquet
    └── validation.json
```

V4 and V9 remain independent. ASV metadata is separated from each wide abundance matrix so
taxonomy queries can scan a small file and abundance queries can project only the requested
sample columns. `manifest.json` records source hashes, schemas, shapes, coverage, artifact hashes,
processing time, and peak memory.

Query-format benchmarking is intentionally separate from preprocessing. It is a development task
that compares raw TSV with Parquet through Polars and DuckDB:

```powershell
uv run python benchmarks/query_formats.py
```

The script prints its JSON report to standard output. DuckDB is a development dependency and is
not required by preprocessing, the API, MCP, or the Agent runtime.

## Deterministic queries

`TaraQueryService` currently provides the first three MVP query capabilities:

- `find_samples`: filter samples by region, polar flag, depth, size fraction, and temperature.
- `get_sample_info`: return complete validated context for one sample ID.
- `find_taxa`: search taxonomy within one explicit marker and aggregate matching raw reads by
  sample.

Taxonomy matching defaults to an exact, case-insensitive classification level. Literal substring
matching must be requested explicitly. Results are bounded by pagination and include provenance,
filter facts, and warnings that sequencing read counts are not cell abundance.

`TaraScientificService` adds the MVP scientific calculations:

- `taxon_abundance`: raw reads and within-sample relative abundance for one marker and taxon.
- `diversity_analysis`: observed ASV richness and natural-log Shannon index, optionally restricted
  to one taxon and summarized by polar status, ocean region, depth, or size fraction.
- `environment_association`: pairwise-complete Spearman correlation between taxon relative
  abundance and one allowlisted numeric environment variable.

V4 and V9 are never combined. Diversity is not rarefied, grouping is descriptive only, and a
single exploratory Spearman test does not apply multiple-testing correction. These limitations and
undefined calculations are returned as machine-readable warnings.

## Run and test

```powershell
uv run fastapi dev
uv run tara-mcp
uv run pytest
uv run ruff check .
```

`tara-mcp` serves the six read-only MVP tools over stdio. Each tool reuses the analysis-layer
Pydantic request and response contracts, so clients receive generated input and output schemas
plus structured results. Set `TARA_PROCESSED_DATA_DIR` when using a non-default processed-data
directory.

## Agent and chat API

Set `DEEPSEEK_API_KEY` in `backend/.env`; the default model is `deepseek-flash` and the default
answer reasoning effort is `low`. The Agent uses a fixed LangGraph workflow: plan one call,
execute one whitelisted MCP tool, then organize the answer. The model never receives source file
access, Python, or SQL execution capabilities.

- `POST /api/v1/chat`: complete structured response.
- `POST /api/v1/chat/stream`: SSE workflow steps, reasoning deltas, and answer deltas followed by
  the complete structured response.
- `GET /api/v1/health`: dataset, Agent, and model readiness.
