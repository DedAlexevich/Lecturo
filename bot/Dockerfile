FROM python:3.12.15-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704

RUN useradd -u 1000 -m app

WORKDIR /app
COPY pyproject.toml requirements.lock ./
RUN python -c "import tomllib; print('\\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > requirements.txt \
    && pip install --no-cache-dir "setuptools>=75" -c requirements.lock -r requirements.txt
COPY app ./app
RUN pip install --no-cache-dir --no-deps --no-build-isolation .

USER app
CMD ["python", "-m", "app.main"]
