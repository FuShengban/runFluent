# config_pass.py

ADMIN_PASSWORD = "123456"  # 管理员密码（用于删除结果等敏感操作）

# ===============================
# NAS SSH 配置（用于删除 NAS 文件）
# ===============================
NAS_SSH_HOST = "100.98.245.17"      # ✅ 改成你的 NAS IP/域名
NAS_SSH_PORT = 22                 # 默认 22
NAS_SSH_USER = "xiaofuzi"            # ✅ 改成你的 NAS SSH 用户
NAS_SSH_PASSWORD = "xiaofuziA5?"  # ✅ 如果用密码登录就填
NAS_SSH_KEYFILE = ""              # ✅ 如果用 key 登录就填私钥路径（如 /root/.ssh/id_rsa），不用则留空
NAS_SSH_TIMEOUT = 10
