# Official documents

This folder holds the TANAPA and Immigration documents SafariAI searches. To add one, put the file here and run this from `backend/`:

    python -m services.cli ingest knowledge/documents/your-file.pdf

If you know the document's title, the dates it's valid for, or that it's an official tariff, add a small file next to it called `your-file.pdf.json`. There's an example in [`docs/ingestion/metadata.example.json`](../../../docs/ingestion/metadata.example.json). SafariAI only quotes a fee from a document marked as official and valid on the visitor's travel date. If you copy fee amounts into that file, use the real figures from the document and never leave the example's zero in place.

You can also upload documents from the **Documents** page in the admin dashboard.
