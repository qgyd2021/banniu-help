## banniu-help

```text
自动审稿。

```

```text
docker build -t banniu-help:v20260520_1150 .

docker stop BanniuHelp && docker rm BanniuHelp

docker run -d \
--name BanniuHelp \
--network host \
--restart always \
-v /home/honeytian/PycharmProjects/banniu-help/temp:/code/temp \
banniu-help:v20260520_1150


```


### 检查项

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

```



```text
http://192.168.34.115:7860/


http://192.168.34.115:7000/portal

http://192.168.34.115:8001/gallery
```