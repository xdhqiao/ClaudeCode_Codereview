# OpenCodeReview 本机运行与 Linux 内网部署手册

## 1. 本机结论

项目 `alibaba/open-code-review` 可以部署到 Windows，但它不是传统常驻后端服务，而是一个 AI 代码审查 CLI 工具，命令名通常是 `ocr`。它读取 Git diff，调用你配置的 LLM 网关，然后输出审查意见；另外提供 `ocr viewer` 在本机或服务器上查看历史审查会话。

我检查的本地代码路径是：

```text
C:\DH\code\open-code-review
```

本地状态：

```text
分支: main
提交: 97de26e, 2026-06-22 19:18:40 +0800
远端: https://github.com/alibaba/open-code-review.git
```

这台 Windows 当前没有检测到 `go`、`node`、`npm`，本地源码目录里也没有 `dist` 或现成的 `ocr.exe`，PATH 中也没有 `ocr` 命令。因此当前机器不能直接从源码构建，也不能直接走 npm 安装。最简单的 Windows 方案是下载官方 Release 的 Windows x64 可执行文件。

由于当前 Codex 会话的 shell 网络访问 GitHub 被限制，我没有成功替你下载运行官方二进制。你手动下载 `ocr.exe` 后，我可以继续帮你验证运行。

## 2. Windows 安装方式

### 方式 A：官方二进制，推荐

这台机器是 AMD64/x64，下载这个文件：

```text
https://github.com/alibaba/open-code-review/releases/latest/download/opencodereview-windows-amd64.exe
```

保存为：

```text
C:\Tools\open-code-review\ocr.exe
```

临时加入当前 PowerShell 会话 PATH：

```powershell
$env:Path += ";C:\Tools\open-code-review"
ocr version
```

长期加入 PATH：打开 Windows 系统环境变量，把 `C:\Tools\open-code-review` 加到用户或系统 PATH。

校验是否可用：

```powershell
ocr version
ocr
```

### 方式 B：通过 npm 安装

前提是先安装 Node.js 20+：

```powershell
npm install -g @alibaba-group/open-code-review
ocr version
```

项目的 npm 包本质上会安装对应平台的原生二进制。

### 方式 C：从源码构建

本地 `go.mod` 要求 Go 1.25：

```powershell
cd C:\DH\code\open-code-review
go build -ldflags "-s -w" -o dist\ocr.exe .\cmd\opencodereview
dist\ocr.exe version
```

如果不能访问公网，需要先准备 Go 模块缓存、内部 GOPROXY，或改用官方二进制。

## 3. Windows 配置 LLM

所有配置默认写入：

```text
%USERPROFILE%\.opencodereview\config.json
```

### OpenAI 兼容网关，例如公司内网模型代理

```powershell
ocr config set provider company-llm
ocr config set custom_providers.company-llm.url http://llm-gateway.company.local/v1
ocr config set custom_providers.company-llm.protocol openai
ocr config set custom_providers.company-llm.model your-model-name
ocr config set custom_providers.company-llm.api_key your-token
ocr config set language Chinese
ocr llm test
```

也可以用旧配置方式：

```powershell
ocr config set llm.url http://llm-gateway.company.local/v1
ocr config set llm.auth_token your-token
ocr config set llm.model your-model-name
ocr config set llm.use_anthropic false
ocr llm test
```

OpenAI 协议下，源码会自动把 base URL 补成 `/chat/completions`，所以 `http://host/v1` 和 `http://host/v1/chat/completions` 都可以。

### Anthropic 兼容网关

```powershell
ocr config set provider company-claude
ocr config set custom_providers.company-claude.url http://claude-gateway.company.local
ocr config set custom_providers.company-claude.protocol anthropic
ocr config set custom_providers.company-claude.model your-claude-model
ocr config set custom_providers.company-claude.auth_header authorization
ocr config set custom_providers.company-claude.api_key your-token
ocr llm test
```

如果你的网关要求 `x-api-key`：

```powershell
ocr config set custom_providers.company-claude.auth_header x-api-key
```

## 4. Windows 使用方法

进入任意 Git 仓库：

```powershell
cd C:\path\to\your-project
```

先预览会审查哪些文件，不调用模型：

```powershell
ocr review --preview
```

审查当前工作区所有未提交变更，包括暂存、未暂存、未跟踪文件：

```powershell
ocr review
```

审查分支差异：

```powershell
ocr review --from main --to feature-branch
```

审查单个提交：

```powershell
ocr review --commit abc123
```

输出 JSON，便于脚本或 CI 处理：

```powershell
ocr review --from main --to feature-branch --format json --audience agent
```

给模型补充业务背景：

```powershell
ocr review --background "这次改动是给登录接口增加限流"
```

打开历史会话查看器：

```powershell
ocr viewer
```

默认访问：

```text
http://localhost:5483
```

历史会话记录保存在：

```text
%USERPROFILE%\.opencodereview\sessions
```

这些记录包含发给模型的提示词、代码片段和模型响应，需要按敏感数据保护。

## 5. 自定义审查规则

项目级规则文件位置：

```text
<your-project>\.opencodereview\rule.json
```

示例：

```json
{
  "rules": [
    {
      "path": "src/main/**/*.java",
      "rule": "重点检查空指针、事务边界、参数校验和异常处理"
    },
    {
      "path": "**/*mapper*.xml",
      "rule": "重点检查 SQL 注入、参数绑定错误、索引风险和动态 SQL 标签闭合"
    }
  ],
  "exclude": [
    "**/generated/**",
    "**/target/**"
  ]
}
```

检查某个文件会匹配什么规则：

```powershell
ocr rules check src/main/java/com/example/UserService.java
```

## 6. Linux 内网服务器部署

### 6.1 推荐定位

建议把 OpenCodeReview 部署在以下位置之一：

- 开发者 Linux 跳板机：人工运行 `ocr review`
- CI Runner 服务器：在 GitLab/Jenkins/GitHub Enterprise 流水线里运行
- 专门的审查工具机：供团队通过 SSH 登录运行

它不适合作为裸露公网 Web 服务运行。`ocr viewer` 只适合内网、VPN 或有认证反代保护的场景。

### 6.2 在线 Linux 服务器直接安装

x86_64 服务器：

```bash
curl -L -o /tmp/ocr https://github.com/alibaba/open-code-review/releases/latest/download/opencodereview-linux-amd64
chmod +x /tmp/ocr
sudo install -m 755 /tmp/ocr /usr/local/bin/ocr
ocr version
```

ARM64 服务器：

```bash
curl -L -o /tmp/ocr https://github.com/alibaba/open-code-review/releases/latest/download/opencodereview-linux-arm64
chmod +x /tmp/ocr
sudo install -m 755 /tmp/ocr /usr/local/bin/ocr
ocr version
```

### 6.3 内网离线部署

在可访问公网的机器下载：

```bash
curl -L -o opencodereview-linux-amd64 https://github.com/alibaba/open-code-review/releases/latest/download/opencodereview-linux-amd64
curl -L -o sha256sum.txt https://github.com/alibaba/open-code-review/releases/latest/download/sha256sum.txt
grep opencodereview-linux-amd64 sha256sum.txt | sha256sum -c -
```

上传到内网服务器：

```bash
scp opencodereview-linux-amd64 user@linux-server:/tmp/ocr
```

在内网服务器安装：

```bash
chmod +x /tmp/ocr
sudo install -m 755 /tmp/ocr /usr/local/bin/ocr
ocr version
```

### 6.4 Linux 配置公司 LLM 网关

推荐用环境变量，适合 CI：

```bash
export OCR_LLM_URL="http://llm-gateway.company.local/v1"
export OCR_LLM_TOKEN="your-token"
export OCR_LLM_MODEL="your-model-name"
export OCR_USE_ANTHROPIC=false
ocr llm test
```

注意：我检查的本地源码里，解析顺序是配置文件优先于 OCR 环境变量。如果同一个 Linux 用户已经存在 `~/.opencodereview/config.json`，它可能覆盖 CI 里设置的环境变量。CI 里建议使用干净用户，或在流水线里显式执行 `ocr config set ...`。

配置文件方式：

```bash
ocr config set provider company-llm
ocr config set custom_providers.company-llm.url http://llm-gateway.company.local/v1
ocr config set custom_providers.company-llm.protocol openai
ocr config set custom_providers.company-llm.model your-model-name
ocr config set custom_providers.company-llm.api_key your-token
ocr config set language Chinese
ocr llm test
```

### 6.5 Linux 使用

```bash
cd /data/repos/your-project
git fetch --all --prune
ocr review --preview
ocr review --from origin/main --to HEAD --format json --audience agent
```

### 6.6 Viewer 内网访问

本机查看：

```bash
ocr viewer
```

内网访问：

```bash
export OCR_VIEWER_ALLOWED_HOSTS="ocr-review.company.local,10.0.0.12"
ocr viewer --addr 0.0.0.0:5483
```

然后通过：

```text
http://ocr-review.company.local:5483
```

访问。

安全建议：

- viewer 没有内置登录认证，不要直接暴露到公网
- 用 Nginx/Ingress 做公司 SSO、Basic Auth 或 VPN 限制
- 会话目录 `~/.opencodereview/sessions` 包含代码片段、提示词和模型响应，应限制文件权限和备份范围

## 7. CI 集成建议

GitLab/Jenkins/内网流水线的核心命令：

```bash
ocr review \
  --from "origin/main" \
  --to "$CI_COMMIT_SHA" \
  --format json \
  --audience agent
```

常见前置条件：

- 拉取完整历史，不能是浅克隆，否则可能找不到 merge-base
- CI 机器必须能访问 Git 仓库和 LLM 网关
- 大 MR 可以降低并发，避免模型网关压力过大：

```bash
ocr review --from origin/main --to "$CI_COMMIT_SHA" --concurrency 4 --format json --audience agent
```

直接使用环境变量时，源码识别的 token 变量名是 `OCR_LLM_TOKEN`。项目示例里出现的 `OCR_LLM_AUTH_TOKEN` 是先作为 CI secret 名称，再通过 `ocr config set llm.auth_token ...` 写入配置。

## 8. 关键注意事项

- 需要 Git；`ocr review` 必须在 Git 仓库里运行，或用 `--repo` 指定仓库。
- 真正调用模型前建议先跑 `ocr review --preview`。
- 大变更会并发调用模型，注意 API 费用、速率限制和网关限流。
- 默认会过滤测试文件、二进制文件、不支持的扩展名、`.gitignore` 排除路径、`node_modules`、`vendor` 等。
- Windows 可运行，但当前机器缺 Go/Node/npm 和二进制；手动放入 `ocr.exe` 后即可继续验证。
- 如果公司要求所有代码不出内网，必须把 `llm.url` 指向内网模型网关，不要配置公网模型 API。
