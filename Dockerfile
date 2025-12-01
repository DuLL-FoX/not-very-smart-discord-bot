FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
	LOG_LEVEL=INFO

RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		ffmpeg \
		libgtk-3-0 \
		libdbus-glib-1-2 \
		libxt6 \
		libx11-xcb1 \
		libasound2 \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip \
	&& pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY cogs/ ./cogs/
COPY utils/ ./utils/
COPY migrations/ ./migrations/

RUN mkdir downloads

CMD ["python3", "main.py"]