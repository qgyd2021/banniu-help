FROM python:3.12

WORKDIR /code

COPY requirements.txt /code/requirements.txt

RUN pip install --upgrade -r /code/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
RUN #pip install --no-cache-dir --upgrade -r /code/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . /code

CMD ["python3", "main.py"]
