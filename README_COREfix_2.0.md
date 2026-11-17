# Corefix 2.2 — Free Demo Studio + Visual Issue Gallery

This is an experience-layer upgrade to the existing Corefix Flask project. The existing Python routes, SQLite schema, report submission flow, rule-based issue categorisation, priority scoring, complaint tracking and heatmap endpoints are retained.

## What's new

- Editorial-style homepage sections with animated workflow visuals and a dashboard preview.
- Scroll progress indicator and scroll-triggered reveal transitions.
- Ambient cursor lighting and subtle pointer-based 3D tilt on showcase panels (desktop; respects reduced-motion preferences).
- Floating Corefix Copilot with guided answers for reporting, ticket tracking, priority scoring, facility locations and admin navigation.
- Quick command palette, opened with `Ctrl+K` (or `⌘+K` on Mac), with keyboard filtering and Enter-to-open.
- Responsive layouts for the new sections and floating assistant.
- The Copilot is local, guided assistance based on the current application's workflows. It is not a connected generative AI model; connecting one requires an API provider and credentials.

## Run locally

1. Extract the ZIP.
2. Open the `corefix` folder in VS Code or a terminal.
3. Create and activate a virtual environment if desired.
4. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

5. Start Flask:

   ```bash
   python app.py
   ```

6. Visit `http://127.0.0.1:5000`.

## Deployment notes

The existing `render.yaml` and application entry point are retained. Keep your existing production database and environment variables when deploying. Set a strong `SECRET_KEY` and `ADMIN_PASSWORD` in Render rather than relying on development defaults.

## Validation performed

- Python bytecode compilation of `app.py`.
- JavaScript syntax checks for `app.js` and `experience.js`.
- Jinja parsing of every template.
- ZIP integrity check.

A full Flask/browser end-to-end test was not run in this build environment because Flask is not installed here. Install the listed requirements and run locally to verify against your environment and database.


## Photo evidence + visual AI assessment

- Reporters can attach up to five JPG, PNG or WEBP photos (5 MB each). File signatures are checked server-side; filenames are replaced with random IDs.
- Selected photos show local previews and can be removed before submission.
- Photos are saved against the issue and shown in the public ticket tracker and admin issue detail.
- Optional visual assessment uses the OpenAI Responses API with a vision-capable model. Set `OPENAI_API_KEY` in the environment; optionally set `OPENAI_VISION_MODEL` (defaults to `gpt-4.1-mini`). The reporter must explicitly press **Analyse with Corefix AI**. The browser never receives the API key.
- The AI returns a visual summary and suggested category/severity. The reporter must review and choose whether to apply the suggestions; they do not silently override form values. AI is not a safety inspection.
- When `OPENAI_API_KEY` is missing, or OpenAI responds with a quota/credit-exhausted error (HTTP 429), Corefix automatically switches to a free local rule-based demo. The demo uses the report text and sample filename to suggest category/severity; it does **not** inspect image pixels and is clearly labelled as demo analysis. It is not generative AI or a safety inspection.
- A six-image sample gallery lets a presenter load illustrative facility issues (damaged sofa, water leak, exposed wiring, loose ceiling light, broken chair, clogged HVAC filter) into the form and run the free demo workflow without uploading their own photos.
- Set `COREFIX_DEMO_MODE=1` to force local demo analysis even if an API key exists. Set it to `0` (default) to use OpenAI when available and automatically fall back when credits are exhausted.
- Configure `UPLOAD_DIR` to a persistent disk path in production. Render's default filesystem is ephemeral; attach a persistent disk and point `UPLOAD_DIR` to its mount path if uploaded evidence must survive redeploys/restarts. Keep uploaded files private to the app and apply an appropriate retention policy.

### Render environment

Add `OPENAI_API_KEY` as a secret environment variable to enable image analysis. Do not commit it to source control. Add a persistent disk and set `UPLOAD_DIR` to its mount path (for example `/var/data/corefix-uploads`) to retain photos across deployments.

`.env.example` is a reference file; this Flask app does not automatically load `.env`. For local PowerShell testing, set the key in the same terminal that starts Flask: `$env:OPENAI_API_KEY="your-key"`, then run `python app.py`. Keep the key out of source control. With no key or exhausted credits, the free local demo path remains available. The API key is used only server-side and is never sent to the browser.
