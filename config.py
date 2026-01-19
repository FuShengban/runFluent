# config.py
# 统一配置：服务端/客户端/监控端共用

# -------- 网络 --------
SERVER_HOST = "47.94.211.70"
SERVER_PORT = 8000
SERVER_BIND_HOST = "0.0.0.0"

# -------- 调度策略 --------
POOL_LIMIT = 100
ASSIGN_BATCH_DEFAULT = 5
UPLOAD_BATCH_DEFAULT = 5

POOL_TARGET_SIZE = POOL_LIMIT 
AUTO_UPLOAD_BATCH = 10
PRODUCER_MIN_LOCAL_COUNT = 20
AUTO_ASSIGN_BATCH = 3
AUTO_ASSIGN_TRIGGER_THRESHOLD = 3

# -------- 本机标识 --------
DEFAULT_NODE_NAME = None  # None 表示自动取当前计算机名

# -------- 模拟参数 --------
FLUENT_DIMENSION = 2
FLUENT_PROCESSORS = 0
TIME_STEP_SIZE = 0.005
WARM_STEPS = 200
SAMPLING_STEPS_INIT = 100
SAMPLING_STEPS_INTERVAL = 50
GUI_FLAG = False

# -------- 收敛判断参数（供 result_is_convergence 使用）--------
CONV_SKIP_STEPS = WARM_STEPS
CONV_TAIL_LENGTH = 150
CONV_RANGE_THRESHOLD = 0.02

# -------- 文件管理 --------
MOVE_MESH_AFTER_RUN = True
FLUENT_RESULT_FILE_PATTERNS = [
    "{stem}.cas",
    "{stem}.dat",
    "{stem}.info",
    "{stem}.plt",
    "{stem}.yplus",
    "{stem}.ascii",
    "{stem}.cas.h5",
    "{stem}.dat.h5",
    "{stem}_cd.out",
    "{stem}_cl.out",
]

# =====================================================================
# 本地优先 + 后台上传到 NAS（Z盘映射）
# =====================================================================

# 是否启用后台上传 + 云端标记
NAS_ENABLE = True

# Z盘是否存在用它判断（映射断开时不影响主线）
NAS_MAPPED_DRIVE = r"Z:\\"
NAS_SOURCE_POOL_DIR = r"Z:\\fluent_pool_source" 

# NAS 映射文件夹内保存结果的根目录
NAS_MAPPED_RESULTS_ROOT = r"Z:\\c2_FluentResults"

# NAS 上真正保存结果文件的根目录
NAS_LINUX_PREFIX = r"/vol1/1007/fluent_cases"

# 上传成功后是否删除本地结果
NAS_DELETE_LOCAL_AFTER_UPLOAD = True

# 上传线程空闲/失败后休眠秒数
NAS_UPLOAD_IDLE_SLEEP_SEC = 10

# 复制重试
NAS_UPLOAD_RETRIES = 6
NAS_UPLOAD_BASE_BACKOFF_SEC = 2.0

# ---------- 改进项 ----------
# (5) 原子上传：先复制到临时目录，再一次性 rename 到最终目录（减少半成品）
NAS_ATOMIC_UPLOAD = True
NAS_TMP_DIRNAME = "_tmp_upload"

# (4) 可选：上传文件白名单（为空表示不限制）
# 例如你只想要 plt + cas/dat + out：
NAS_UPLOAD_EXT_WHITELIST = []  # e.g. [".plt", ".cas.h5", ".dat.h5", ".out", ".cas", ".dat"]

# (6) UI 刷新上传队列状态的间隔（毫秒）
UI_UPLOAD_STATUS_REFRESH_MS = 2000

# ------- Auto-mode by done-signal (no fixed 5min) -------
AUTO_POLL_MS = 3000  # 客户端轮询完成信号的间隔
CASE_DONE_SIGNAL_FILE = "case_done.signal"  # 写入“刚完成的case”的信号文件（本机即可）

# -------- NAS SFTP 配置 --------
NAS_SFTP_HOST = "100.98.245.17"
NAS_SFTP_PORT = 22
NAS_SFTP_USER = "xiaofuzi"
NAS_SFTP_KEY_PATH = r".\\id_ed25519_nas"

# NAS上的绝对路径
NAS_POOL_PATH = "/vol1/1007/fluent_cases/fluent_pool_source"
NAS_RESULTS_PATH = "/vol1/1007/fluent_cases/c2_FluentResults"
