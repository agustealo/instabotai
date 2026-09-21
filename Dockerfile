FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9

ARG INSTABOTAI_EXTRAS=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system instabotai \
    && useradd --system --gid instabotai --create-home instabotai

COPY pyproject.toml README.md LICENSE LICENSE_PREMIUM ./
COPY instabotai ./instabotai

RUN python -m pip install --upgrade pip \
    && if [ -n "$INSTABOTAI_EXTRAS" ]; then \
         python -m pip install ".[${INSTABOTAI_EXTRAS}]"; \
       else \
         python -m pip install .; \
       fi \
    && chown -R instabotai:instabotai /app

USER instabotai

ENTRYPOINT ["instabotai"]
CMD ["doctor"]
