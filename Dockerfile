FROM --platform=linux/arm64/v8 python:3.12.8-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Обновляем список пакетов и устанавливаем FFmpeg
RUN apt-get update && apt-get install -y ffmpeg

# Копируем файлы зависимостей и устанавливаем их
COPY requirements.txt requirements.txt
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Копируем файлы приложения
COPY main.py .
COPY .env .
COPY cogs/ ./cogs/
COPY utils/ ./utils/

# Создаем директорию для загрузок
RUN mkdir downloads

# Задаем команду для запуска бота
CMD ["python3", "main.py"]