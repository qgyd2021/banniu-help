FROM python:3.12

WORKDIR /code

RUN apt-get update
RUN apt-get install -y --no-install-recommends nodejs
RUN rm -rf /var/lib/apt/lists/*

COPY requirements.txt /code/requirements.txt

RUN pip install --upgrade -r /code/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . /code

CMD ["python3", "main.py"]
