"""启动时：探测本机局域网 IP，并在终端打印访问地址。

手机与本机在同一局域网/WiFi 即可通过浏览器访问。
"""
from __future__ import annotations

import ipaddress
import socket


def _collect_private_ips() -> list[str]:
    """收集本机所有 IPv4 私网地址（排除回环/链路本地）。"""
    ips: list[str] = []
    seen = set()

    # 方式1：遍历所有 hostname 解析出的地址
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip in seen:
                continue
            seen.add(ip)
            try:
                addr = ipaddress.ip_address(ip)
                if addr.is_private and not addr.is_loopback and not addr.is_link_local:
                    ips.append(ip)
            except ValueError:
                continue
    except Exception:
        pass

    # 方式2：通过连外部地址拿到默认出口 IP（可能拿到 VPN/公网 IP，作为备选）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        default_ip = s.getsockname()[0]
        s.close()
        if default_ip not in seen:
            seen.add(default_ip)
            try:
                addr = ipaddress.ip_address(default_ip)
                if addr.is_private and not addr.is_loopback:
                    ips.insert(0, default_ip)  # 放在最前面优先用
                elif not addr.is_loopback:
                    ips.append(default_ip)  # 非私网也保留（比如公网 IP 可直接访问）
            except ValueError:
                pass
    except Exception:
        pass

    # 方式3：兜底——至少返回 127.0.0.1
    if not ips:
        ips.append("127.0.0.1")

    return ips


def get_lan_ip() -> str:
    """返回第一个可用的局域网 IP。"""
    ips = _collect_private_ips()
    # 优先返回私网 IP（192.168.x.x / 10.x.x.x / 172.16-31.x.x）
    for ip in ips:
        try:
            addr = ipaddress.ip_address(ip)
            if addr.is_private and not addr.is_loopback:
                return ip
        except ValueError:
            continue
    return ips[0]


def print_access_banner(port: int) -> str:
    """在终端打印访问地址，返回首选访问 URL。"""
    ips = _collect_private_ips()
    primary = get_lan_ip()
    primary_url = f"http://{primary}:{port}"

    print("\n" + "=" * 50)
    print("  🖨️ 918实验室云打印 已启动")
    print("=" * 50)
    print(f"  电脑/手机浏览器访问： {primary_url}")
    print(f"  本机也可访问：        http://127.0.0.1:{port}")

    # 如果有多个 IP（多网卡/VPN 环境），列出其他可能的地址供用户选择
    other_ips = [ip for ip in ips if ip != primary and ip != "127.0.0.1"]
    if other_ips:
        print("\n  检测到多个网络接口，其他可用地址：")
        for ip in other_ips:
            print(f"    • http://{ip}:{port}")

    print("\n  💡 提示：手机需连同一 WiFi，或直接复制地址到浏览器")
    print("=" * 50 + "\n")
    return primary_url
