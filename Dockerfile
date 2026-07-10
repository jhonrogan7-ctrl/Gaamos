FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements-dev.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
# Non-root runtime user (defense-in-depth; independent of host rootless mapping)
RUN useradd --create-home --uid 10001 app
COPY . .
RUN bash bin/build-css.sh build \
    && python manage.py collectstatic --noinput \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app
EXPOSE 8000
USER app
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
