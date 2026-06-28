FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# 数据目录（挂载持久化）
VOLUME ["/data"]
ENV DB_PATH=/data/weibo.db
ENV STOCK_ALIAS_PATH=/data/stock_alias.json

EXPOSE 8848
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8848"]
