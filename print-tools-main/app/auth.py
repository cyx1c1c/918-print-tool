"""登录认证：密码校验、会话管理、防暴力破解。

全部使用 Python 标准库（secrets / hmac / hashlib / time），不引入任何第三方依赖，
保证能随项目一起打包成单个 exe。

设计要点：
- 密码既支持「明文」（管理员图省事直接写），也支持 `pbkdf2_sha256$...` 哈希
  （想更安全时用 `python -m app.auth` 生成后粘贴进配置）。校验一律走常量时间比较。
- 会话存在服务端内存（单进程 uvicorn 足够）；进程重启后需重新登录，对打印站可接受。
- 防爆破按来源 IP 计失败次数，超阈值锁定一段时间；并对每次失败加固定小延迟拖慢脚本。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

COOKIE_NAME = "pt_session"

# pbkdf2 哈希串前缀与参数
_HASH_PREFIX = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 200_000


# ============================ 密码 ============================
def hash_password(plain: str, *, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """把明文密码转成可存进配置文件的哈希串。

    格式：``pbkdf2_sha256$<迭代次数>$<盐 hex>$<哈希 hex>``
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iterations)
    return f"{_HASH_PREFIX}${iterations}${salt.hex()}${dk.hex()}"


def _verify_hashed(plain: str, stored: str) -> bool:
    """校验 `pbkdf2_sha256$...` 形式的哈希密码。"""
    try:
        algo, iter_s, salt_hex, hash_hex = stored.split("$", 3)
        if algo != _HASH_PREFIX:
            return False
        iterations = int(iter_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)


def verify_password(plain: str, stored: str) -> bool:
    """校验密码：stored 是哈希则按哈希比，否则按明文常量时间比较。"""
    if not stored:
        return False
    if stored.startswith(_HASH_PREFIX + "$"):
        return _verify_hashed(plain, stored)
    return hmac.compare_digest(plain.encode("utf-8"), stored.encode("utf-8"))


def verify_username(given: str, expected: str) -> bool:
    """用户名也用常量时间比较，避免按耗时枚举用户名。"""
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


# ============================ 会话 ============================
_sessions: dict[str, float] = {}  # token -> 过期时间（epoch 秒）


def _purge_expired_sessions(now: float | None = None) -> None:
    now = time.time() if now is None else now
    for tok in [t for t, exp in _sessions.items() if exp <= now]:
        _sessions.pop(tok, None)


def create_session(ttl_seconds: int) -> str:
    """新建会话，返回随机 token（登录成功后调用，天然防会话固定）。"""
    _purge_expired_sessions()
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + ttl_seconds
    return token


def validate_session(token: str | None) -> bool:
    """校验 token 是否有效且未过期；顺带惰性清理过期项。"""
    if not token:
        return False
    exp = _sessions.get(token)
    if exp is None:
        return False
    if exp <= time.time():
        _sessions.pop(token, None)
        return False
    return True


def destroy_session(token: str | None) -> None:
    if token:
        _sessions.pop(token, None)


# ============================ 防爆破（按 IP） ============================
_attempts: dict[str, tuple[int, float]] = {}  # ip -> (失败次数, 锁定截止 epoch)


def check_locked(ip: str) -> int:
    """返回该 IP 还需锁定的剩余秒数；0 表示未锁定。"""
    rec = _attempts.get(ip)
    if not rec:
        return 0
    _, locked_until = rec
    remaining = int(locked_until - time.time())
    return remaining if remaining > 0 else 0


def record_failure(ip: str, max_attempts: int, lockout_seconds: int) -> None:
    """记一次登录失败；达到阈值则锁定该 IP 一段时间。"""
    fails, _ = _attempts.get(ip, (0, 0.0))
    fails += 1
    locked_until = time.time() + lockout_seconds if fails >= max_attempts else 0.0
    _attempts[ip] = (fails, locked_until)


def record_success(ip: str) -> None:
    """登录成功，清空该 IP 的失败记录。"""
    _attempts.pop(ip, None)


# ============================ CLI：生成哈希密码 ============================
def _main() -> None:
    import getpass

    pwd = getpass.getpass("请输入要加密的密码：")
    if not pwd:
        print("密码为空，已取消。")
        return
    again = getpass.getpass("再输入一次确认：")
    if pwd != again:
        print("两次输入不一致，已取消。")
        return
    print("\n把下面这行整体粘贴到 config.ini 的 password = 后面：\n")
    print(hash_password(pwd))


if __name__ == "__main__":
    _main()
