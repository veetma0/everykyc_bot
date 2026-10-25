FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home bot \
    && mkdir /app/data && chown bot:bot /app/data
COPY --chown=bot:bot verifydesk ./verifydesk
USER bot
CMD ["python", "-m", "verifydesk"]
