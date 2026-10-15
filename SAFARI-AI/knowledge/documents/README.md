Place TANAPA publications here and index them with:

    python -m services.cli ingest knowledge/documents/your-file.pdf

Add `your-file.pdf.json` beside the file when you know the title, effective dates, and authority. A fee is quoted only if that sidecar says `authority` is `official` and the effective window covers the question date. An example sidecar is in `docs/ingestion/metadata.example.json`. Replace the example amount with figures you transcribed from the publication. Do not leave the placeholder zero in a file you index.
