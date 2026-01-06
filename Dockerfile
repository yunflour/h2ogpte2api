FROM python:3.9-slim
ENV TZ=Asia/Shanghai

WORKDIR /app

RUN apt-get update && apt-get install -y git

RUN git clone https://github.com/yunflour/h2ogpte2api /app

RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

RUN chmod -R 777 /app

CMD ["python", "main.py"]