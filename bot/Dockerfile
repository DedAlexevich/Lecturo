FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > requirements.txt \
    && pip install --no-cache-dir setuptools -r requirements.txt
COPY app ./app
RUN pip install --no-cache-dir --no-deps --no-build-isolation .

CMD ["python", "-m", "app.main"]
