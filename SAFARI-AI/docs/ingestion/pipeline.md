# Ingestion

```text
file -> extract -> clean -> classify -> metadata -> chunk -> embed -> store
```

PDF extraction uses `pypdf`. Text and Markdown are read directly. Cleaning collapses whitespace. Classification is a keyword pass over the filename and the first part of the text (tariff, guideline, procedure, brochure, and the other TANAPA publication classes).

A sidecar named `<file>.json` supplies the metadata that classification cannot know:

- `effective_from`, `effective_until`, `status`, `version`
- `authority` (`official` is required before a fee row can be quoted)
- `fees` when a tariff has been transcribed into rows

Chunks are about 900 characters with paragraph boundaries preserved. Each chunk copies the parent document's authority, status, and effective window so retrieval can filter without a join.

Drop files into `knowledge/documents/` and index them with:

```bash
python -m services.cli ingest knowledge/documents/your-file.pdf
```

The catalog of 21 parks is seeded on startup. Those document ids start with `tanapa_park_` and are refreshed from `knowledge/metadata/parks.json`.
