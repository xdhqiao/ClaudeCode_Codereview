# OpenCodeReview 公司内网 Linux 部署方案

## 结论

`alibaba/open-code-review` 更适合按 CLI 工具部署，而不是按后端服务部署。Linux 服务器上只需要安装一个 `ocr` 可执行文件，再配置模型网关和 Git 仓库访问权限即可运行审查。只有 `ocr viewer` 会启动 HTTP 端口，用于查看历史审查会话。

本地代码版本：

- 路径：`C:\DH\code\open-code-review`
- 当前提交：`97de26e`
- 运行入口：`cmd/opencodereview`
- Go 要求：`go.mod` 中声明 `go 1.25.0`
- 生成 Linux 二进制：`Makefile` 支持 `build-linux-amd64` 和 `build-linux-arm64`

## 一、推荐部署方式

### 方案 A：使用官方 Linux 二进制，推荐

适合生产和内网服务器。优点是不需要在服务器安装 Go/Node/npm。

x86_64：

```bash
curl -L -o /tmp/ocr https://github.com/alibaba/open-code-review/releases/latest/download/opencodereview-linux-amd64
chmod +x /tmp/ocr
sudo install -m 755 /tmp/ocr /usr/local/bin/ocr
ocr version
```

ARM64：

```bash
curl -L -o /tmp/ocr https://github.com/alibaba/open-code-review/releases/latest/download/opencodereview-linux-arm64
chmod +x /tmp/ocr
sudo install -m 755 /tmp/ocr /usr/local/bin/ocr
ocr version
```

### 方案 B：离线部署，适合严格内网

在能访问公网的机器下载：

```bash
curl -L -o opencodereview-linux-amd64 https://github.com/alibaba/open-code-review/releases/latest/download/opencodereview-linux-amd64
curl -L -o sha256sum.txt https://github.com/alibaba/open-code-review/releases/latest/download/sha256sum.txt
grep opencodereview-linux-amd64 sha256sum.txt | sha256sum -c -
```

上传到内网制品库或目标服务器：

```bash
scp opencodereview-linux-amd64 user@linux-server:/tmp/ocr
```

服务器安装：

```bash
chmod +x /tmp/ocr
sudo install -m 755 /tmp/ocr /usr/local/bin/ocr
ocr version
```

### 方案 C：从源码构建

服务器或构建机需要 Go 1.25+、git、make。

```bash
cd /opt/src/open-code-review
make build
sudo install -m 755 dist/opencodereview /usr/local/bin/ocr
ocr version
```

跨平台产物：

```bash
make build-linux-amd64
make build-linux-arm64
```

## 二、服务器运行用户与目录建议

建议创建专用用户：

```bash
sudo useradd -m -s /bin/bash ocr
sudo mkdir -p /data/repos
sudo chown -R ocr:ocr /data/repos
```

默认配置和历史目录在运行用户家目录：

```text
~/.opencodereview/config.json
~/.opencodereview/sessions/
```

`sessions` 中会保存模型请求、代码片段和模型响应，应按敏感数据保护。

## 三、配置公司内网模型网关

### OpenAI 兼容网关

```bash
ocr config set provider company-llm
ocr config set custom_providers.company-llm.url http://llm-gateway.company.local/v1
ocr config set custom_providers.company-llm.protocol openai
ocr config set custom_providers.company-llm.model your-model-name
ocr config set custom_providers.company-llm.api_key your-token
ocr config set language Chinese
ocr llm test
```

源码会把 OpenAI 兼容 URL 自动补成 `/chat/completions`，所以配置到 `/v1` 通常即可。

### DeepSeek

如果内网服务器允许访问 DeepSeek 公网 API，或公司有 DeepSeek 代理：

```bash
export DEEPSEEK_API_KEY="your-token"
ocr config set provider deepseek
ocr config set model deepseek-v4-pro
ocr config set language Chinese
ocr llm test
```

如需写入配置文件：

```bash
ocr config set providers.deepseek.api_key "$DEEPSEEK_API_KEY"
```

### 纯环境变量方式

适合 CI。注意本地源码解析顺序是配置文件优先，然后才是 OCR 环境变量；CI 中建议设置独立 `HOME`，避免被已有用户配置影响。

```bash
export HOME="$PWD/.ocr-home"
export OCR_LLM_URL="http://llm-gateway.company.local/v1"
export OCR_LLM_TOKEN="your-token"
export OCR_LLM_MODEL="your-model-name"
export OCR_USE_ANTHROPIC=false
ocr llm test
```

## 四、人工使用

```bash
cd /data/repos/your-project
git fetch --all --prune
ocr review --preview
ocr review --from origin/main --to HEAD
```

常用命令：

```bash
ocr review
ocr review --from origin/main --to feature-branch
ocr review --commit abc123
ocr review --format json --audience agent
ocr review --concurrency 4 --timeout 20
```

## 五、GitLab CI 使用

核心要求：

- `GIT_DEPTH=0`，否则可能找不到 merge-base
- CI Runner 能访问 Git 仓库和 LLM 网关
- token 用 GitLab masked variable 保存

最小示例：

```yaml
stages:
  - review

ocr-review:
  stage: review
  only:
    - merge_requests
  variables:
    GIT_DEPTH: "0"
  script:
    - export HOME="$CI_PROJECT_DIR/.ocr-home"
    - export OCR_LLM_URL="$OCR_LLM_URL"
    - export OCR_LLM_TOKEN="$OCR_LLM_AUTH_TOKEN"
    - export OCR_LLM_MODEL="${OCR_LLM_MODEL:-your-model-name}"
    - export OCR_USE_ANTHROPIC=false
    - ocr llm test
    - |
      ocr review \
        --from "origin/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME}" \
        --to "${CI_COMMIT_SHA}" \
        --format json \
        --audience agent \
        --concurrency 4 \
        > ocr-result.json
  artifacts:
    when: always
    paths:
      - ocr-result.json
```

如果要把评论自动写回 GitLab MR，可以基于项目自带 `examples/gitlab_ci/.gitlab-ci.yml` 改造。

## 六、Viewer 内网访问

本机查看：

```bash
ocr viewer
```

默认地址：

```text
http://localhost:5483
```

内网访问：

```bash
export OCR_VIEWER_ALLOWED_HOSTS="ocr-review.company.local,10.0.0.12"
ocr viewer --addr 0.0.0.0:5483
```

建议通过 Nginx 加认证：

```nginx
server {
    listen 80;
    server_name ocr-review.company.local;

    auth_basic "OpenCodeReview";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:5483;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

systemd 示例：

```ini
[Unit]
Description=OpenCodeReview Viewer
After=network.target

[Service]
User=ocr
Environment=OCR_VIEWER_ALLOWED_HOSTS=ocr-review.company.local
ExecStart=/usr/local/bin/ocr viewer --addr 127.0.0.1:5483
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## 七、安全与运维注意事项

- 不要把 viewer 暴露到公网。
- `~/.opencodereview/config.json` 含 token 时必须限制权限。
- `~/.opencodereview/sessions` 可能含源代码、提示词和模型响应。
- 大 MR 建议降低并发：`--concurrency 2` 或 `--concurrency 4`。
- 全内网合规场景下，`llm.url` 必须指向公司内网模型网关，不要直连公网模型 API。
- 如果 CI 变量名叫 `OCR_LLM_AUTH_TOKEN`，运行 `ocr` 前要映射成源码实际识别的 `OCR_LLM_TOKEN`。
