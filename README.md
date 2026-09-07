# FalixNodes 自动重启脚本

# ⭐ **觉得有用？给个 Star 支持一下！**
> 注册地址：[https://falixnodes.net/](https://client.falixnodes.net/auth/register)

自动检查并重启 FalixNodes 服务器的 GitHub Actions 脚本。支持多账号、代理、Telegram 通知等功能。

## ✨ 功能特性

- ✅ 多账号支持
- ✅ 自动登录（处理 Cloudflare Turnstile 验证）
- ✅ 智能检测服务器状态（offline/unknown 自动重启）
- ✅ 支持代理访问（Hysteria2）
- ✅ Telegram 通知（带截图）
- ✅ 自动处理 Cookie 弹窗和广告


## 📋 前置要求

### 1. GitHub Secrets 配置

进入仓库 `Settings` → `Secrets and variables` → `Actions`，添加以下 Secrets：

| Secret 名称 | 必填 | 说明 | 示例 |
|------------|------|------|------|
| `FALIX` | ✅ | FalixNodes 账号信息 | 见下方格式 |
| `TG_BOT_TOKEN` | ❌ | Telegram Bot Token | `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11` |
| `TG_CHAT_ID` | ❌ | Telegram Chat ID | `123456789` |
| `HY2_URL` | ❌ | Hysteria2 代理地址 | `hysteria2://password@server:port?sni=example.com` |

### 2. FALIX 格式

每行一个账号，格式：`邮箱-----密码`

```
admin@example.com-----your_password_123
user@domain.com-----another_password
```

### 3. Telegram 通知配置（可选）

1. 创建 Bot：[@BotFather](https://t.me/BotFather) 发送 `/newbot`
2. 获取 Chat ID：[@userinfobot](https://t.me/userinfobot) 发送任意消息
3. 将 Bot Token 和 Chat ID 添加到 Secrets

## 🚀 使用方法

### 方法 1：手动触发（GitHub 网页）

1. 进入仓库的 `Actions` 页面
2. 选择 `FalixNodes 重启` 工作流
3. 点击 `Run workflow`
4. （可选）在 `指定邮箱` 输入框填写邮箱（留空则处理全部账号）
5. 点击绿色的 `Run workflow` 按钮

### 方法 2：API 调用

#### 运行全部账号

```bash
curl -X POST \
  -H "Authorization: Bearer ghp_XXXXXXXXXXXXXXXXXXXXXXXXX" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/你的用户名/你的仓库名/actions/workflows/falix.yml/dispatches \
  -d '{"ref":"main"}'
```

#### 指定账号执行

```bash
curl -X POST \
  -H "Authorization: Bearer ghp_XXXXXXXXXXXXXXXXXXXXXXXXX" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/oyz8/FalixNodes/actions/workflows/Falix_Restart.yml/dispatches \
  -d '{
    "ref": "main",
    "inputs": {
      "accounts": "admin@example.com"
    }
  }'
```

#### 多个账号（逗号分隔）

```bash
curl -X POST \
  -H "Authorization: Bearer ghp_XXXXXXXXXXXXXXXXXXXXXXXXX" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/oyz8/FalixNodes/actions/workflows/Falix_Restart.yml/dispatches \
  -d '{
    "ref": "main",
    "inputs": {
      "accounts": "admin@example.com,user@domain.com"
    }
  }'
```

### 方法 3：定时任务

在 `.github/workflows/falix.yml` 中添加 `schedule` 触发器：

```yaml
on:
  workflow_dispatch:
    inputs:
      accounts:
        description: '指定邮箱（留空全部，多个用逗号）'
        required: false
  schedule:
    - cron: '0 */6 * * *'  # 每 6 小时执行一次
```

常用 cron 表达式：
- `0 */6 * * *` - 每 6 小时
- `0 0 * * *` - 每天 0 点
- `0 0,12 * * *` - 每天 0 点和 12 点


## 📱 Telegram 通知示例

### 单个服务器
```
✅ 成功
账号: admin@example.com
信息: 检查 1 个服务器，重启 1 个
服务器: 2873336，重启成功 (starting)
时间: 2025-01-08 12:32:38

FalixNodes Auto Restart
```
*附带服务器控制台截图*

### 多个服务器
```
✅ 成功
账号: admin@example.com
信息: 检查 3 个服务器，重启 2 个
服务器: 2873336，重启成功 (starting)
服务器: 2871237，在线 (running)
服务器: 2883456，重启成功 (starting)
时间: 2025-01-08 12:32:38

FalixNodes Auto Restart
```
*附带每个服务器的控制台截图（最多10张）*

## 🔧 高级配置

### 修改重试次数

编辑 `scripts/Falix/main.py`：

```python
AD_RETRY_LIMIT = 10  # 默认 10 次，可改为其他值
```

## 🐛 常见问题

### 1. 登录失败

**原因**：
- 账号密码错误
- Turnstile 验证失败
- 网络问题

**解决**：
- 检查 `FALIX` Secret 格式是否正确
- 查看 Actions 日志中的截图
- 尝试配置代理（`HY2_URL`）

### 2. 重启失败

**原因**：
- 服务器处于特殊状态
- 广告弹窗干扰
- 网络延迟

**解决**：
- 脚本会自动重试 10 次
- 检查 Artifacts 中的截图
- 增加 `AD_RETRY_LIMIT` 值

### 3. Telegram 通知未收到

**原因**：
- Bot Token 或 Chat ID 错误
- Bot 未启动对话

**解决**：
- 在 Telegram 中向 Bot 发送 `/start`
- 验证 Secret 配置是否正确
- 检查 Actions 日志中的错误信息

### 4. 代理连接失败

**原因**：
- `HY2_URL` 格式错误
- 代理服务器不可用

**解决**：
- 验证 Hysteria2 配置格式
- 测试代理服务器连通性
- 留空 `HY2_URL` 使用直连模式


### 服务器状态说明

| 状态 | 说明 | 操作 |
|------|------|------|
| `offline` | 离线 | ✅ 重启 |
| `unknown` | 未知 | ✅ 重启 |
| `starting` | 启动中 | ⏭️ 跳过 |
| `running` | 运行中 | ⏭️ 跳过 |
| `online` | 在线 | ⏭️ 跳过 |

## 🔒 安全建议

1. ✅ **使用 GitHub Secrets** 存储敏感信息
2. ✅ **定期更新密码** 并同步到 Secrets
3. ✅ **限制 GitHub Token 权限**（仅 `repo` 和 `workflow`）
4. ✅ **开启仓库私有** 防止信息泄露
5. ✅ **定期检查 Actions 运行日志**

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

**⚠️ 免责声明**：本脚本仅供学习交流使用，使用者需遵守 FalixNodes 的服务条款。因使用本脚本造成的任何问题，作者不承担任何责任。
