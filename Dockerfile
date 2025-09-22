FROM python:3.13-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Unbuffered Python stdout/stderr for better logging in containers
ENV PYTHONUNBUFFERED=1 \
	LOG_LEVEL=INFO

# Обновляем список пакетов и устанавливаем FFmpeg без рекомендуемых пакетов
RUN apt-get update \
	&& apt-get install -y --no-install-recommends ffmpeg \
	&& rm -rf /var/lib/apt/lists/*

# Копируем файлы зависимостей и устанавливаем их
COPY requirements.txt requirements.txt
RUN pip install --upgrade pip \
	&& pip install --no-cache-dir -r requirements.txt

# Копируем файлы приложения
COPY main.py .
COPY cogs/ ./cogs/
COPY utils/ ./utils/

# Создаем директорию для загрузок
RUN mkdir downloads

# Задаем команду для запуска бота
CMD ["python3", "main.py"]