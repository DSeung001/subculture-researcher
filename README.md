# Subculture Researcher

Private MVP for collecting and reviewing anime / figure / goods / collection content.

## Architecture

```
Python collector
      ↓
   Firestore
      ↑
  Streamlit
```

The first version intentionally avoids a separate backend server.

## MVP features

- RSS collection into Firestore
- URL-based deduplication using SHA-256 document IDs
- Manual URL capture from the Streamlit sidebar
- Categories:
  - `ANIME`
  - `CHARACTER`
  - `FIGURE`
  - `GOODS`
  - `COLLECTION`
- Content angles such as `NEWS`, `SIZE`, `PRICE`, and `QUESTION`
- Research workflow:
  - `NEW`
  - `KEEP`
  - `HOLD`
  - `IGNORE`

## 1. Firebase setup

1. Create a Firebase project.
2. Enable **Cloud Firestore**.
3. In Firebase Console, create/download a service account key.
4. Keep the JSON file outside Git or name it `firebase-key.json` in this project.
5. Point Application Default Credentials to it.

macOS / Linux:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$PWD/firebase-key.json"
```

PowerShell:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS="$PWD\firebase-key.json"
```

The key is ignored by `.gitignore`. Never commit it.

## 2. Install

Python 3.11+ is recommended.

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

## 3. Add sources

Edit `sources.yaml`.

```yaml
sources:
  - name: example
    type: rss
    url: https://example.com/feed.xml
    category: ANIME
    enabled: true
```

Only add sources after confirming their terms and automated-access policy.

## 4. Collect

```bash
python collect.py
```

Each URL becomes a deterministic Firestore document ID, so rerunning the collector does not create duplicate documents for the same URL.

## 5. Run dashboard

```bash
streamlit run app.py
```

Use the sidebar to manually save URLs or filter collected content.

## Firestore shape

```
contents/{sha256(url)}
  url
  title
  summary
  source
  sourceType
  category
  contentAngle
  status
  publishedAt
  collectedAt
  createdAt
```

## Intentionally not in V0

- X scraping
- Auto-posting
- LLM summarization
- Recommendation models
- Vector DB
- Authentication
- Separate API/backend server
- Scheduled cloud jobs

The next milestone should be adding 3-5 real sources and using the inbox for several days before adding automation.
