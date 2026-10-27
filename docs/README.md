# docs/

This directory holds project architecture and demo documentation.

The following files will be added here in later steps:

- **ARCHITECTURE.md** -- full system design, data flow, and table schemas.
  Note: any sections in ARCHITECTURE.md that reference a CLI entrypoint are
  superseded by the HTTP API plus Streamlit design. The backend is always
  reached through FastAPI; there is no standalone CLI.
- **DEMO_DATA.md** -- guide to the fictional demo dataset in data/teams/ and
  data/notes/, and instructions for running the end-to-end demo.
