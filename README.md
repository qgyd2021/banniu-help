## banniu-help

```text
自动审稿。

```

```text
banniu-help:v20260528_1145
docker build -t banniu-help:v20260529_1453 .
docker build -t banniu-help:v20260529_1638 .
docker build -t banniu-help:v20260530_1945 .
docker build -t banniu-help:v20260603_1058 .
docker build -t banniu-help:v20260603_1506 .
docker build -t banniu-help:v20260609_1133 .
docker build -t banniu-help:v20260609_1212 .
docker build -t banniu-help:v20260622_1012 .
docker build -t banniu-help:v20260622_1800 .

docker stop BanniuHelp && docker rm BanniuHelp

docker run -d \
--name BanniuHelp \
--network host \
--restart always \
-v /home/honeytian/PycharmProjects/banniu-help/temp:/code/temp \
banniu-help:v20260622_1800


```


### 外部依赖

依赖 ollama
```text
检查 ollama 是否能成功访问：

curl -X POST http://127.0.0.1:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ollama" \
  -d '{
    "model": "qwen2.5:14b-instruct",
    "messages": [{"role": "user", "content": "你好，请简单介绍一下自己"}],
    "max_tokens": 50
  }'

nvidia-smi

```

依赖 OpenUltralytics

```text

https://www.modelscope.cn/studios/qgyd2021/OpenUltralytics

已将其部署在本地服务器。
访问：http://192.168.34.115:7861/



```


```text

http://127.0.0.1:18001/gallery
http://192.168.208.104:18001/gallery

http://192.168.34.115:7860/
http://192.168.34.115:17000/portal
http://192.168.34.115:18001/gallery


https://cdn.mchose.com.cn/customPage/sharelink/index.html#/submit

```

