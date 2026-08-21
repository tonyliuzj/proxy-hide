FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system proxyhide \
    && useradd --system --gid proxyhide --home-dir /app proxyhide

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-cache-dir .

USER proxyhide
EXPOSE 8000 9000

CMD ["python", "-m", "app.runtime"]
