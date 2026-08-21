FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# Fonts are a runtime dependency of the QR poster renderer (menu/dashboard/
# poster.py), not a convenience: the base image ships none at all, and without
# them Pillow silently falls back to a bitmap face that cannot scale to print
# size. Caladea/Liberation are the serifs (both have LINING figures, so a room
# "101" prints as digits); Montserrat is the gaamos.io wordmark.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gettext \
        fonts-crosextra-caladea \
        fonts-liberation \
        fonts-montserrat \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-dev.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
# Non-root runtime user (defense-in-depth; independent of host rootless mapping)
RUN useradd --create-home --uid 10001 app
COPY . .
RUN python manage.py compilemessages \
    && bash bin/build-css.sh build \
    && python manage.py collectstatic --noinput \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app
EXPOSE 8000
USER app
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
