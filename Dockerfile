FROM python:3.8

RUN pip install --upgrade pip

ENV PYTHONUNBUFFERED 1
RUN mkdir /code

WORKDIR /code
COPY . /code/

RUN pip install -r requirements.txt

COPY ./entrypoint.sh /
ENTRYPOINT ["sh", "/entrypoint.sh"]