"""Обработчик подписок Nemo VPN.
Интегрирован из nemo-sub, теперь работает внутри вебхук-сервера.
"""

import asyncio
import base64
import json
import urllib.parse
import sqlite3
import re
from typing import Optional, List
from aiohttp import web
from loguru import logger
import os

from config import settings

# VLESS-шаблоны
STANDARD_OUTBOUND = {
    "protocol": "vless",
    "settings": {
        "vnext": [{
            "address": settings.XUI_HOST,
            "port": settings.XUI_PORT_STANDARD,
            "users": [{
                "id": "{uuid}",
                "encryption": "none",
                "flow": "xtls-rprx-vision"
            }]
        }]
    },
    "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
            "show": False,
            "fingerprint": "chrome",
            "serverName": settings.XUI_SNI_STANDARD,
            "publicKey": settings.XUI_PBK_STANDARD,
            "shortId": settings.XUI_SID_STANDARD,
            "spiderX": ""
        }
    },
    "tag": "proxy"
}

HAPP_ROUTING = {
    "domain": [
        "happ_routing_standard",
        "happ_routing_premium",
        "happ_routing_unified"
    ]
}

def _get_db_path() -> str:
    return "/etc/x-ui/x-ui.db"

def _read_xui_db() -> dict:
    """Читает клиентов из SQLite x-ui."""
    clients = {}
    try:
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT id, settings FROM inbounds")
        for row in cur.fetchall():
            try:
                inbound_settings = json.loads(row["settings"])
                for cl in inbound_settings.get("clients", []):
                    email = cl.get("email")
                    uuid = cl.get("id")
                    if email and uuid:
                        clients[email] = {
                            "uuid": uuid,
                            "inbound_id": row["id"],
                            "email": email,
                        }
            except:
                continue
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка чтения x-ui DB: {e}")
    return clients


def _build_vless_link(client: dict, port: int, sni: str, pbk: str, sid: str, flow: str = "xtls-rprx-vision") -> str:
    """Собирает VLESS-ссылку."""
    params = urllib.parse.urlencode({
        "type": "tcp" if port == settings.XUI_PORT_STANDARD else "grpc",
        "security": "reality",
        "pbk": pbk,
        "fp": "chrome",
        "sni": sni,
        "sid": sid,
    }, safe=":")
    if flow and port == settings.XUI_PORT_STANDARD:
        params += f"&flow={urllib.parse.quote(flow, safe='')}".replace("%2B", "+")
    return f"vless://{client['uuid']}@{settings.XUI_HOST}:{port}?{params}#NemoVPN-{client['email']}"


def _build_happ_routing(tier: str) -> str:
    """Возвращает happ://routing/add/ URL."""
    routing_b64 = base64.b64encode(json.dumps(HAPP_ROUTING, indent=2).encode()).decode()
    return f"happ://routing/add/{routing_b64}"


class SubscriptionHandler:
    """Обработчик подписок (бывший nemo-sub)."""

    async def handle_subscription(self, request: web.Request) -> web.Response:
        """GET /sub/<path> — возвращает VLESS-ссылки + happ routing.
        Путь — это email клиента из x-ui.
        """
        try:
            path = request.match_info.get("path", "")
            if not path or not re.match(r"^[a-zA-Z0-9_\-]+", path):
                return web.Response(status=404, text="Not found")

            clients = _read_xui_db()
            client = clients.get(path)
            if not client:
                return web.Response(status=404, text="Client not found")

            # Формируем подписку
            lines = []
            # Standard (443, Reality)
            vless_std = _build_vless_link(
                client,
                port=settings.XUI_PORT_STANDARD,
                sni=settings.XUI_SNI_STANDARD,
                pbk=settings.XUI_PBK_STANDARD,
                sid=settings.XUI_SID_STANDARD,
                flow="xtls-rprx-vision"
            )
            lines.append(vless_std)

            # Premium (9999, Reality)
            vless_prem = _build_vless_link(
                client,
                port=settings.XUI_PORT_PREMIUM,
                sni=settings.XUI_SNI_PREMIUM,
                pbk=settings.XUI_PBK_PREMIUM,
                sid=settings.XUI_SID_PREMIUM,
                flow=""
            )
            lines.append(vless_prem)

            # Happ routing
            lines.append(_build_happ_routing("standard"))

            content = "\n".join(lines)
            return web.Response(
                body=content,
                headers={
                    "Content-Type": "text/plain; charset=utf-8",
                    "Profile-Title": "Nemo VPN",
                    "Profile-Update-Interval": "12",
                    "Subscription-Userinfo": f"upload=0; download=0; total=0; expire=0",
                }
            )
        except Exception as e:
            logger.error(f"Subscription error: {e}")
            return web.Response(status=500, text="Internal error")


subscription_handler = SubscriptionHandler()
