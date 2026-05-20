## banniu-help

```text
自动审稿。

```

```text
docker build -t banniu-help:v20260519_1227 .

docker stop BanniuHelp && docker rm BanniuHelp

docker run -d \
--name BanniuHelp \
--network host \
--restart always \
-v /home/banniu-help/temp:/code/temp
-e UPLOAD_MEDIA_PREFIX=webdriver/sharelink \
-e PORT=18082 \
banniu-help:v20260519_1227

docker run -itd \
--name BanniuHelp \
--network host \
-e UPLOAD_MEDIA_PREFIX=webdriver/sharelink \
-e PORT=18082 \
banniu-help:v20260515_1539 \
/bin/bash


```
