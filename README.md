# Web-Development

## Deploying on Render

Render needs a start command to run your web service. Add the following start command in the Render dashboard or include a `Procfile` in the repo (this project includes one):

web: gunicorn app:app --bind 0.0.0.0:$PORT

Notes:

- Render provides the port via the `$PORT` environment variable, so the bind flag is required.
- Make sure `gunicorn` is installed (it's included in `requirements.txt`).
