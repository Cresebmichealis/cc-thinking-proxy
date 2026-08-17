# Claude Code Thinking Chain 可视化指南

## 问题

Claude Code 从 2026年2月12日起默认隐藏思考链（thinking chain）。它在每个API请求中发送 `anthropic-beta: redact-thinking-2026-02-12` header，告诉服务器不要返回思考内容。

即使开了 `alwaysThinkingEnabled: true`（让Claude总是思考），你在终端里也看不到思考过程——因为内容在服务端就被过滤掉了。

## 解决方案

**先试方案A，一行设置就够了。** 我们绕了一整天搓代理才发现这个开关存在——别重蹈覆辙。

---

### 方案A：showThinkingSummaries 设置（一行搞定，实测可用）

Claude Code 有一个内置设置 `showThinkingSummaries`。开启后，CC会自动去掉 `redact-thinking` header，并在请求中设置 `thinking.display: "summarized"`。

**步骤：**

1. 打开 `~/.claude/settings.json`（即 `C:\Users\你的用户名\.claude\settings.json`）

2. 添加：
```json
{
  "showThinkingSummaries": true,
  "alwaysThinkingEnabled": true
}
```

3. 重启 Claude Code

**实测结果（2026年8月）：** Pro订阅用户实测可用，重启后即可在终端看到thinking内容。GitHub Issue #52376 曾提到subscription用户可能收到空thinking块，但截至2026年8月已不再是问题。

**如果方案A对你不生效，再用方案B。**

---

### 方案B：本地代理（实测可用）

原理：在本地起一个代理服务器，拦截所有发往 Anthropic API 的请求，剥掉 `redact-thinking` 相关的 header，然后转发给真正的API。

#### 架构

```
Claude Code  -->  本地代理 (127.0.0.1:8099)  -->  api.anthropic.com
                    在这里剥掉 redact-thinking header
```

#### Step 1：代理代码

保存为 `proxy.py`：

```python
"""
Streaming SSE Proxy v2
"""
import http.server
import http.client
import json
import ssl

LISTEN_PORT = 8099
TARGET_HOST = "api.anthropic.com"
TARGET_PORT = 443
REDACT_STR = "redact-thinking"

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _forward(self, method):
        cl = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(cl) if cl > 0 else None
        hdrs = {}
        stripped = False
        for k, v in self.headers.items():
            lk = k.lower()
            if lk == 'host':
                hdrs[k] = TARGET_HOST
                continue
            if lk == 'anthropic-beta':
                parts = [p.strip() for p in v.split(',')]
                filtered = [p for p in parts if REDACT_STR not in p]
                if len(filtered) < len(parts):
                    stripped = True
                    print(f"  [STRIP] {v} -> {', '.join(filtered) if filtered else '(empty)'}")
                if filtered:
                    hdrs[k] = ', '.join(filtered)
                continue
            hdrs[k] = v
        print(f"\n[PROXY] {method} {self.path}" + (" *stripped*" if stripped else ""))
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(TARGET_HOST, TARGET_PORT, context=ctx, timeout=300)
        try:
            conn.request(method, self.path, body=body, headers=hdrs)
            resp = conn.getresponse()
            self.send_response(resp.status)
            is_sse = False
            for k2, v2 in resp.getheaders():
                lk2 = k2.lower()
                if lk2 == 'transfer-encoding':
                    continue
                if lk2 == 'content-type' and 'text/event-stream' in v2:
                    is_sse = True
                self.send_header(k2, v2)
            if is_sse:
                self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            if is_sse:
                print("  [SSE] Streaming...")
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        self.wfile.write(b'0\r\n\r\n')
                        self.wfile.flush()
                        break
                    hl = format(len(chunk), 'x')
                    self.wfile.write(f"{hl}\r\n".encode())
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                print("  [SSE] Stream ended")
            else:
                data = resp.read()
                self.wfile.write(data)
                self.wfile.flush()
        except Exception as e:
            print(f"  [ERR] {e}")
            try:
                self.send_response(502)
                self.end_headers()
                msg = json.dumps({"error": str(e)})
                self.wfile.write(msg.encode())
            except Exception:
                pass
        finally:
            conn.close()

    def do_POST(self): self._forward('POST')
    def do_GET(self): self._forward('GET')
    def do_OPTIONS(self): self._forward('OPTIONS')
    def do_DELETE(self): self._forward('DELETE')
    def do_PUT(self): self._forward('PUT')
    def do_PATCH(self): self._forward('PATCH')
    def log_message(self, fmt, *a): pass

def main():
    srv = http.server.HTTPServer(('127.0.0.1', LISTEN_PORT), Handler)
    print("=" * 55)
    print("  SSE Proxy v2")
    print("=" * 55)
    print(f"  Listen:  http://127.0.0.1:{LISTEN_PORT}")
    print(f"  Target:  https://{TARGET_HOST}")
    print(f"  Strip:   '{REDACT_STR}' from anthropic-beta")
    print()
    print("  Ctrl+C to stop")
    print("=" * 55)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        srv.shutdown()

if __name__ == '__main__':
    main()
```

#### Step 2：配置 Claude Code

在 `~/.claude/settings.json` 的 `env` 块里添加：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8099"
  },
  "alwaysThinkingEnabled": true
}
```

#### Step 3：启动

**手动：** 先开终端运行 `python proxy.py`，再开 Claude Code。

**一键 bat 文件（Windows）：**

```batch
@echo off
chcp 65001 >nul
echo Starting thinking proxy...
start "Thinking Proxy" /min python "path\to\proxy.py"
timeout /t 2 /nobreak >nul
cd /d %USERPROFILE%
claude --model claude-opus-4-6
echo Stopping proxy...
taskkill /fi "windowtitle eq Thinking Proxy" >nul 2>&1
pause
```

#### 验证

代理终端打印 `*stripped*` = header成功剥掉。

---

## 踩过的坑

| 问题 | 原因 | 解法 |
|---|---|---|
| CC报API错误 | HTTP/1.0不支持chunked transfer | 设 `protocol_version = 'HTTP/1.1'` |
| 响应卡住 | 没实时转发SSE chunk | `resp.read(4096)` 循环 + flush |
| settings.json静默失效 | env嵌套两层 | `"env": {}` 只一层 |
| 端口冲突 | 代理已在跑 | 不要同时运行两个proxy |
| 写不了文件 | Auto mode classifier拦截代理相关内容 | 手动编辑或切acceptEdits模式 |

## 已知限制

- **方案B的重大缺陷：** 代理会导致 Claude Code 的 auto mode classifier 不可用。Classifier 负责判断工具调用是否安全——挂了之后所有写入操作（Write、Edit、Bash写文件、PowerShell写文件）都会被拦截，Claude 几乎无法正常工作。需要手动切换到 `acceptEdits` 模式才能绕过，但会失去自动安全检查。**因此强烈建议用方案A。**
- `showThinkingSummaries` 如果对你的账户类型生效，不需要代理。实测Pro订阅可用（2026年8月）。

## 相关链接

- [GitHub Issue #52376 - Enable thinking.display for subscription sessions](https://github.com/anthropics/claude-code/issues/52376)
- [GitHub Issue #32997 - Thinking redaction and deceptive behavior](https://github.com/anthropics/claude-code/issues/32997)
- [HypoGray - Why Claude Code hides its thinking](https://hypogray.com/stories/claude-code-hides-thinking)
- [ClaudeLog FAQ - Why can't I see Claude thinking?](https://claudelog.com/faqs/why-cant-i-see-claude-thinking/)
