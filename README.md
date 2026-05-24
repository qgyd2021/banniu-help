## banniu-help

```text
自动审稿。

```

```text
docker build -t banniu-help:v20260524_1001 .

docker stop BanniuHelp && docker rm BanniuHelp

docker run -d \
--name BanniuHelp \
--network host \
--restart always \
-v /home/honeytian/PycharmProjects/banniu-help/temp:/code/temp \
banniu-help:v20260524_1001


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

http://127.0.0.1:18001/gallery

http://192.168.34.115:17000/portal

http://192.168.34.115:18001/gallery
```



### 下载贴子BadCase

```text
douyin

9.43 06/29 g@B.GV EuF:/ :9pm 太好了，太棒了，到了到了# 迈从 # 迈从A7V2  https://v.douyin.com/za3mLgMkh3Y/ 复制此链接，打开Dou音搜索，直接观看视频！


```
