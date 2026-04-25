# -*- coding: utf-8 -*-
import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import socket
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, List

import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

try:
    from proton import SSLDomain
    from proton.handlers import MessagingHandler
    from proton.reactor import Container

    HAS_PROTON = True
except Exception:
    SSLDomain = None
    Container = None

    class MessagingHandler:  # fallback placeholder so class definitions do not crash
        def __init__(self, *args, **kwargs):
            pass

    HAS_PROTON = False


@dataclass
class AliyunConfig:
    backend_mode: str = "local_relay"
    product_key: str = ""
    device_name: str = ""
    device_secret: str = ""
    region: str = "cn-shanghai"
    consumer_group_id: str = ""
    access_key_id: str = ""
    access_key_secret: str = ""
    amqp_endpoint: str = ""
    amqp_queue: str = "DefaultQueue"
    amqp_instance_id: str = ""
    mqtt_host: str = ""
    mqtt_port: int = 8883
    mqtt_tls: bool = True
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_client_id: str = ""
    mqtt_sign_type: str = "1"
    local_relay_enable: bool = True
    local_relay_host: str = "127.0.0.1"
    local_relay_port: int = 19091


def _env(name: str, default: str = ""):
    return str(os.getenv(name, default) or "").strip()


def _env_bool(name: str, default: bool):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


DASHBOARD_ACCESS_FLAG_PATH = os.path.join(
    os.path.dirname(__file__), ".dashboard_access"
)


def dashboard_access_enabled(default: bool = True):
    raw_env = os.getenv("DASHBOARD_ACCESS_ENABLED")
    if raw_env is not None and str(raw_env).strip() != "":
        return str(raw_env).strip().lower() in {"1", "true", "yes", "y", "on", "enable", "enabled"}

    if not os.path.exists(DASHBOARD_ACCESS_FLAG_PATH):
        return default

    try:
        with open(DASHBOARD_ACCESS_FLAG_PATH, "r", encoding="utf-8") as f:
            raw = (f.read() or "").strip().lower()
        if raw in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
            return True
        if raw in {"0", "false", "no", "n", "off", "disable", "disabled"}:
            return False
    except Exception:
        pass

    return default


def _load_dotenv(path: str):
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


def _env_cloud(primary: str, legacy: str, default: str = ""):
    value = _env(primary, "")
    if value:
        return value
    return _env(legacy, default)


def load_huawei_config():
    _load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    relay_port_raw = _env("LOCAL_RELAY_PORT", "19091")
    try:
        relay_port = int(relay_port_raw)
    except Exception:
        relay_port = 19091
    mqtt_port_raw = _env_cloud("HUAWEI_MQTT_PORT", "ALIYUN_MQTT_PORT", "8883")
    try:
        mqtt_port = int(mqtt_port_raw)
    except Exception:
        mqtt_port = 8883

    return AliyunConfig(
        backend_mode=_env_cloud("HUAWEI_BACKEND_MODE", "ALIYUN_BACKEND_MODE", "local_relay").lower(),
        product_key=_env_cloud("HUAWEI_PRODUCT_KEY", "ALIYUN_PRODUCT_KEY", "a17MwdB5xAq"),
        device_name=_env_cloud("HUAWEI_DEVICE_NAME", "ALIYUN_DEVICE_NAME", "web_socket"),
        device_secret=_env_cloud("HUAWEI_DEVICE_SECRET", "ALIYUN_DEVICE_SECRET", ""),
        region=_env_cloud("HUAWEI_REGION", "ALIYUN_REGION", "cn-shanghai"),
        consumer_group_id=_env_cloud("HUAWEI_CONSUMER_GROUP_ID", "ALIYUN_CONSUMER_GROUP_ID", ""),
        access_key_id=_env_cloud("HUAWEI_ACCESS_KEY_ID", "ALIYUN_ACCESS_KEY_ID", ""),
        access_key_secret=_env_cloud("HUAWEI_ACCESS_KEY_SECRET", "ALIYUN_ACCESS_KEY_SECRET", ""),
        amqp_endpoint=_env_cloud("HUAWEI_AMQP_ENDPOINT", "ALIYUN_AMQP_ENDPOINT", ""),
        amqp_queue=_env_cloud("HUAWEI_AMQP_QUEUE", "HUAWEI_CONSUMER_GROUP_ID", "DefaultQueue"),
        amqp_instance_id=_env_cloud("HUAWEI_AMQP_INSTANCE_ID", "ALIYUN_AMQP_INSTANCE_ID", ""),
        mqtt_host=_env_cloud("HUAWEI_MQTT_HOST", "ALIYUN_MQTT_HOST", ""),
        mqtt_port=mqtt_port,
        mqtt_tls=_env_bool("HUAWEI_MQTT_TLS", True),
        mqtt_username=_env_cloud("HUAWEI_MQTT_USERNAME", "ALIYUN_MQTT_USERNAME", ""),
        mqtt_password=_env_cloud("HUAWEI_MQTT_PASSWORD", "ALIYUN_MQTT_PASSWORD", ""),
        mqtt_client_id=_env_cloud("HUAWEI_MQTT_CLIENT_ID", "ALIYUN_MQTT_CLIENT_ID", ""),
        mqtt_sign_type=_env_cloud("HUAWEI_MQTT_SIGN_TYPE", "ALIYUN_MQTT_SIGN_TYPE", "1"),
        local_relay_enable=_env_bool("LOCAL_RELAY_ENABLE", True),
        local_relay_host=_env("LOCAL_RELAY_HOST", "127.0.0.1"),
        local_relay_port=relay_port,
    )


def detect_lan_ipv4s():
    ips = set()

    # Primary route interface (works even without real UDP traffic).
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            ips.add(sock.getsockname()[0])
        finally:
            sock.close()
    except Exception:
        pass

    # Hostname resolution fallback.
    try:
        host = socket.gethostname()
        for item in socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM):
            ip = item[4][0]
            if ip:
                ips.add(ip)
    except Exception:
        pass

    def _usable(ip: str):
        try:
            addr = ipaddress.ip_address(ip)
            return (
                isinstance(addr, ipaddress.IPv4Address)
                and not addr.is_loopback
                and not addr.is_link_local
                and addr.is_private
            )
        except Exception:
            return False

    return sorted([ip for ip in ips if _usable(ip)])


class AliyunServiceAmqpBridge:
    class _Handler(MessagingHandler):
        def __init__(self, bridge: "AliyunServiceAmqpBridge"):
            super().__init__(auto_accept=True)
            self.bridge = bridge
            self.conn = None

        def on_start(self, event):
            ts = str(int(time.time() * 1000))
            user = self.bridge._build_username(ts)
            password = self.bridge._build_password(ts)
            url = self.bridge._build_url()
            if not url:
                self.bridge._emit(
                    {
                        "type": "status",
                        "message": "AMQP config missing: HUAWEI_AMQP_ENDPOINT",
                        "time": int(time.time()),
                    }
                )
                return

            ssl_domain = SSLDomain(SSLDomain.MODE_CLIENT)
            ssl_domain.set_peer_authentication(SSLDomain.VERIFY_PEER)

            self.conn = event.container.connect(
                url=url,
                user=user,
                password=password,
                ssl_domain=ssl_domain,
                heartbeat=30,
            )
            queue_name = self.bridge.cfg.amqp_queue or "DefaultQueue"
            event.container.create_receiver(self.conn, queue_name)
            self.bridge._emit(
                {
                    "type": "status",
                    "message": (
                        f"Connecting Huawei AMQP: {url}, queue={queue_name}"
                    ),
                    "time": int(time.time()),
                }
            )

        def on_message(self, event):
            body = event.message.body
            if isinstance(body, bytes):
                text = body.decode("utf-8", errors="ignore")
            else:
                text = str(body)

            payload: Dict[str, Any] | Any
            try:
                payload = json.loads(text)
            except Exception:
                payload = {"raw": text}

            self.bridge._emit(
                {
                    "type": "mqtt",
                    "topic": "amqp/service-subscription",
                    "payload": payload,
                    "time": int(time.time()),
                }
            )

        def on_transport_error(self, event):
            self.bridge._emit(
                {
                    "type": "status",
                    "message": f"AMQP transport error: {event.transport.condition}",
                    "time": int(time.time()),
                }
            )

        def on_connection_error(self, event):
            self.bridge._emit(
                {
                    "type": "status",
                    "message": f"AMQP connection error: {event.connection.remote_condition}",
                    "time": int(time.time()),
                }
            )

    def __init__(self, cfg: AliyunConfig, loop: asyncio.AbstractEventLoop):
        self.cfg = cfg
        self.loop = loop
        self.queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._thread: threading.Thread | None = None
        self._container = None

    def _build_url(self):
        endpoint = self.cfg.amqp_endpoint.strip()
        if not endpoint:
            return ""
        if endpoint.startswith("amqps://"):
            base = endpoint
        else:
            base = f"amqps://{endpoint}"
        if "?" in base:
            return base
        return f"{base}?amqp.vhost=default&amqp.idleTimeout=8000&amqp.saslMechanisms=PLAIN"

    def _build_username(self, timestamp: str):
        base = f"accessKey={self.cfg.access_key_id}|timestamp={timestamp}"
        if self.cfg.amqp_instance_id:
            return f"{base}|instanceId={self.cfg.amqp_instance_id}"
        return base

    def _build_password(self, timestamp: str):
        return self.cfg.access_key_secret

    def start(self):
        if not HAS_PROTON:
            self._emit(
                {
                    "type": "status",
                    "message": "python-qpid-proton is not installed. Please install requirements_amqp_optional.txt",
                    "time": int(time.time()),
                }
            )
            return

        handler = AliyunServiceAmqpBridge._Handler(self)
        self._container = Container(handler)
        self._thread = threading.Thread(target=self._container.run, daemon=True)
        self._thread.start()

    def stop(self):
        container = self._container
        if container is not None:
            try:
                container.stop()
            except Exception:
                pass
        self._container = None

    def _emit(self, data: Dict[str, Any]):
        self.loop.call_soon_threadsafe(self.queue.put_nowait, data)


class StatusOnlyBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop, messages: List[str]):
        self.loop = loop
        self.queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self.messages = messages

    def start(self):
        for text in self.messages:
            self.queue.put_nowait(
                {
                    "type": "status",
                    "message": text,
                    "time": int(time.time()),
                }
            )

    def stop(self):
        return


class AliyunWsMqttBridge:
    def __init__(self, cfg: AliyunConfig, loop: asyncio.AbstractEventLoop):
        self.cfg = cfg
        self.loop = loop
        self.client: mqtt.Client | None = None
        self.queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._mid_to_topic: Dict[int, str] = {}
        self._last_disconnect_ts = 0
        self._disconnect_burst = 0

    @staticmethod
    def _build_auth(product_key: str, device_name: str, device_secret: str, sign_type: str = "1"):
        sign_type = str(sign_type or "1").strip()
        timestamp = time.strftime("%Y%m%d%H", time.gmtime())
        client_id = f"{device_name}_0_{sign_type}_{timestamp}"
        username = device_name
        password = hmac.new(
            device_secret.encode("utf-8"),
            timestamp.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        return client_id, username, password

    def start(self):
        host = self.cfg.mqtt_host.strip()
        if not host:
            self._emit(
                {
                    "type": "status",
                    "message": "Huawei MQTT config missing: HUAWEI_MQTT_HOST",
                    "time": int(time.time()),
                }
            )
            return
        port = int(self.cfg.mqtt_port or 8883)

        if self.cfg.mqtt_username and self.cfg.mqtt_password and self.cfg.mqtt_client_id:
            client_id = self.cfg.mqtt_client_id
            username = self.cfg.mqtt_username
            password = self.cfg.mqtt_password
        else:
            if not self.cfg.device_name or not self.cfg.device_secret:
                self._emit(
                    {
                        "type": "status",
                        "message": "Huawei MQTT missing: HUAWEI_DEVICE_NAME / HUAWEI_DEVICE_SECRET",
                        "time": int(time.time()),
                    }
                )
                return
            client_id, username, password = self._build_auth(
                self.cfg.product_key,
                self.cfg.device_name,
                self.cfg.device_secret,
                self.cfg.mqtt_sign_type,
            )

        client = mqtt.Client(client_id=client_id, clean_session=True)
        if username:
            client.username_pw_set(username=username, password=password)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.on_subscribe = self._on_subscribe
        client.reconnect_delay_set(min_delay=1, max_delay=8)
        if self.cfg.mqtt_tls or port == 8883:
            client.tls_set()
        client.connect(host, port=port, keepalive=60)
        client.loop_start()
        self.client = client

        self._emit(
            {
                "type": "status",
                "message": f"Connecting Huawei MQTT: {host}:{port}",
                "time": int(time.time()),
            }
        )

    def stop(self):
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
        self.client = None

    def _on_connect(self, client: mqtt.Client, userdata, flags, rc):
        if rc == 0:
            topics = [
                f"$oc/devices/{self.cfg.device_name}/sys/#",
            ]
            for topic in topics:
                _, mid = client.subscribe(topic, qos=1)
                self._mid_to_topic[mid] = topic

            self._emit(
                {
                    "type": "status",
                    "message": "Huawei MQTT connected and subscribed",
                    "topics": topics,
                    "time": int(time.time()),
                }
            )
        else:
            self._emit(
                {
                    "type": "status",
                    "message": f"Huawei MQTT connect failed, rc={rc}",
                    "time": int(time.time()),
                }
            )

    def _on_disconnect(self, client: mqtt.Client, userdata, rc):
        now = int(time.time())
        if self._last_disconnect_ts and now - self._last_disconnect_ts <= 3:
            self._disconnect_burst += 1
        else:
            self._disconnect_burst = 1
        self._last_disconnect_ts = now

        reason = ""
        if rc == 7:
            reason = " (connection lost; possible device credential conflict or network reset)"

        extra = ""
        if self._disconnect_burst >= 3:
            extra = (
                " High-frequency disconnect detected. "
                "If qt.py and web_dashboard.py use the same ProductKey+DeviceName, "
                "Cloud platform may force one connection offline."
            )

        self._emit(
            {
                "type": "status",
                "message": f"Huawei MQTT disconnected, rc={rc}{reason}{extra}",
                "time": int(time.time()),
            }
        )

    def _on_subscribe(self, client: mqtt.Client, userdata, mid, granted_qos):
        topic = self._mid_to_topic.get(mid, "unknown")
        if granted_qos and granted_qos[0] == 128:
            self._emit(
                {
                    "type": "status",
                    "message": (
                        f"Subscribe denied: topic={topic}, qos={granted_qos}. "
                        "Please check Topic permission in Huawei IoT console."
                    ),
                    "time": int(time.time()),
                }
            )
            return

        self._emit(
            {
                "type": "status",
                "message": f"Subscribe ack: topic={topic}, mid={mid}, qos={granted_qos}",
                "time": int(time.time()),
            }
        )

    def _on_message(self, client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
        raw = msg.payload.decode("utf-8", errors="ignore")
        payload: Dict[str, Any] | Any
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}

        data = {
            "type": "mqtt",
            "topic": msg.topic,
            "payload": payload,
            "time": int(time.time()),
        }
        self._emit(data)

    def _emit(self, data: Dict[str, Any]):
        self.loop.call_soon_threadsafe(self.queue.put_nowait, data)


class LocalRelayUdpBridge:
    def __init__(self, cfg: AliyunConfig, loop: asyncio.AbstractEventLoop):
        self.cfg = cfg
        self.loop = loop
        self.queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self):
        if not self.cfg.local_relay_enable:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._emit(
            {
                "type": "status",
                "message": (
                    f"Local relay listening: udp://{self.cfg.local_relay_host}:{self.cfg.local_relay_port}"
                ),
                "time": int(time.time()),
            }
        )

    def _run(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind((self.cfg.local_relay_host, self.cfg.local_relay_port))
            self._sock = sock
        except Exception as exc:
            self._emit(
                {
                    "type": "status",
                    "message": f"Local relay bind failed: {exc}",
                    "time": int(time.time()),
                }
            )
            return

        while self._running:
            try:
                raw, addr = self._sock.recvfrom(8192)
                text = raw.decode("utf-8", errors="ignore")
                payload: Dict[str, Any] | Any
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = {"raw": text}

                self._emit(
                    {
                        "type": "mqtt",
                        "topic": f"local/relay/{addr[0]}:{addr[1]}",
                        "payload": payload,
                        "time": int(time.time()),
                    }
                )
            except OSError:
                break
            except Exception as exc:
                self._emit(
                    {
                        "type": "status",
                        "message": f"Local relay recv error: {exc}",
                        "time": int(time.time()),
                    }
                )

    def stop(self):
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None

    def _emit(self, data: Dict[str, Any]):
        self.loop.call_soon_threadsafe(self.queue.put_nowait, data)


def _extract_params(payload: Dict[str, Any]):
    if not isinstance(payload, dict):
        return None

    if isinstance(payload.get("params"), dict):
        return payload.get("params")
    if isinstance(payload.get("items"), dict):
        return payload.get("items")
    if isinstance(payload.get("data"), dict):
        return payload.get("data")
    services = payload.get("services")
    if isinstance(services, list) and services:
        first = services[0]
        if isinstance(first, dict):
            props = first.get("properties")
            if isinstance(props, dict):
                normalized = {}
                if "soil_moisture" in props:
                    normalized["SoilMoisture"] = props.get("soil_moisture")
                if "current_humidity" in props:
                    normalized["CurrentHumidity"] = props.get("current_humidity")
                if "current_temperature" in props:
                    normalized["CurrentTemperature"] = props.get("current_temperature")
                if "co2" in props:
                    normalized["co2"] = props.get("co2")
                if "light_lux" in props:
                    normalized["LightLux"] = props.get("light_lux")
                return normalized if normalized else props

    return payload


class ConnectionHub:
    def __init__(self):
        self.clients: List[WebSocket] = []
        self.latest: Dict[str, Any] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.append(ws)
        if self.latest:
            await ws.send_json({"type": "latest", "data": self.latest})

    def disconnect(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)

    async def broadcast(self, data: Dict[str, Any]):
        if data.get("type") == "mqtt":
            payload = data.get("payload")
            if isinstance(payload, dict):
                params = _extract_params(payload)
                if isinstance(params, dict):
                    air = params.get("air1") if isinstance(params.get("air1"), dict) else {}
                    self.latest = {
                        "SoilMoisture": params.get("SoilMoisture", params.get("soil", "-")),
                        "CurrentHumidity": params.get("CurrentHumidity", air.get("h", "-")),
                        "CurrentTemperature": params.get("CurrentTemperature", air.get("t", "-")),
                        "co2": params.get("co2", "-"),
                        "LightLux": params.get("LightLux", params.get("light", "-")),
                    }

        dead = []
        for ws in self.clients:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)


hub = ConnectionHub()


def build_primary_bridge(cfg: AliyunConfig, loop: asyncio.AbstractEventLoop):
    mode = (cfg.backend_mode or "").lower()
    if mode in {"local", "relay", "local_relay", "qt_relay"}:
        return StatusOnlyBridge(
            loop,
            [
                "Local relay mode enabled: Web dashboard listens UDP relay from qt.py only."
            ],
        )

    if mode == "amqp":
        missing = []
        if not cfg.amqp_endpoint:
            missing.append("HUAWEI_AMQP_ENDPOINT")
        if not cfg.access_key_id:
            missing.append("HUAWEI_ACCESS_KEY_ID")
        if not cfg.access_key_secret:
            missing.append("HUAWEI_ACCESS_KEY_SECRET")
        if missing:
            return StatusOnlyBridge(
                loop,
                [f"AMQP config missing: {', '.join(missing)}"],
            )
        if not HAS_PROTON:
            return StatusOnlyBridge(
                loop,
                [
                    "AMQP mode requires python-qpid-proton. Please install requirements_amqp_optional.txt"
                ],
            )
        return AliyunServiceAmqpBridge(cfg=cfg, loop=loop)

    if mode in {"mqtt", "mqtt_ws", "wss", "mqtts"}:
        if not cfg.mqtt_host:
            return StatusOnlyBridge(
                loop,
                [
                    "MQTT config missing: HUAWEI_MQTT_HOST"
                ],
            )
        has_manual = bool(cfg.mqtt_username and cfg.mqtt_password and cfg.mqtt_client_id)
        has_auto = bool(cfg.device_name and cfg.device_secret)
        if not (has_manual or has_auto):
            return StatusOnlyBridge(
                loop,
                [
                    "MQTT config missing: "
                    "either HUAWEI_MQTT_USERNAME/HUAWEI_MQTT_PASSWORD/HUAWEI_MQTT_CLIENT_ID "
                    "or HUAWEI_DEVICE_NAME/HUAWEI_DEVICE_SECRET"
                ],
            )
        return AliyunWsMqttBridge(cfg=cfg, loop=loop)

    return StatusOnlyBridge(
        loop,
        [
            f"Unknown HUAWEI_BACKEND_MODE={cfg.backend_mode}, expected local_relay / amqp / mqtt_ws"
        ],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    cfg = load_huawei_config()

    primary_bridge = build_primary_bridge(cfg=cfg, loop=loop)
    bridges = [primary_bridge]

    if cfg.local_relay_enable:
        bridges.append(LocalRelayUdpBridge(cfg=cfg, loop=loop))

    app.state.bridges = bridges
    for bridge in app.state.bridges:
        bridge.start()

    for bridge in app.state.bridges:
        bridge.queue.put_nowait(
            {
                "type": "status",
                "message": (
                    f"Bridge online: {bridge.__class__.__name__}, "
                    f"mode={cfg.backend_mode}, region={cfg.region}, "
                    f"pk={cfg.product_key or '-'}, queue={cfg.amqp_queue or '-'}"
                ),
                "time": int(time.time()),
            }
        )

    async def fanout_task(queue: asyncio.Queue[Dict[str, Any]]):
        while True:
            msg = await queue.get()
            await hub.broadcast(msg)

    app.state.fanouts = [
        asyncio.create_task(fanout_task(bridge.queue)) for bridge in app.state.bridges
    ]

    try:
        yield
    finally:
        for task in getattr(app.state, "fanouts", []):
            task.cancel()
        for bridge in getattr(app.state, "bridges", []):
            bridge.stop()


app = FastAPI(title="Huawei IoT Web Dashboard", lifespan=lifespan)


DASHBOARD_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Huawei IoT 实时看板</title>
  <style>
    :root {
      --bg: #f2f5fb;
      --surface: #ffffff;
      --line: #d8e2f0;
      --text: #31445a;
      --muted: #6d7f96;
      --title: #18314f;
      --good: #1f9d6a;
      --warn: #f5a524;
      --bad: #e5484d;
      --blue: #2b82ff;
      --orange: #f97316;
      --red: #ef4444;
      --green: #22a06b;
      --violet: #8b5cf6;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: var(--bg); color: var(--text); }
    .wrap { max-width: 1320px; margin: 16px auto 26px; padding: 0 12px; }
    .band { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 12px; margin-bottom: 10px; }
    .title { margin: 0; color: var(--title); font-size: clamp(24px, 4vw, 42px); line-height: 1.05; font-weight: 800; letter-spacing: 0; }
    .subtitle { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
    .status-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 10px; }
    .chip { border: 1px solid var(--line); border-radius: 999px; padding: 4px 10px; font-size: 12px; color: var(--muted); background: #f8fbff; white-space: nowrap; }
    .chip.ok { color: #0f8a5f; border-color: #bdebd7; background: #ecfbf4; }
    .chip.warn { color: #9f6a00; border-color: #f8db9d; background: #fff8e9; }
    .chip.bad { color: #b3262d; border-color: #f7c8cb; background: #fff0f1; }
    .alert-panel { border: 1px solid #f7d0d2; background: #fff5f5; border-radius: 10px; padding: 10px; display: none; }
    .alert-title { color: #b3262d; font-weight: 700; font-size: 13px; margin-bottom: 6px; }
    .alert-list { margin: 0; padding-left: 18px; color: #8f2a2f; font-size: 12px; }
    .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; }
    .metric { min-height: 146px; border: 1px solid var(--line); border-radius: 10px; padding: 11px; background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%); }
    .metric-hd { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); }
    .metric-value { margin-top: 8px; display: flex; align-items: baseline; gap: 6px; }
    .metric-value strong { font-size: 38px; line-height: 1; color: var(--title); font-weight: 800; letter-spacing: 0; }
    .unit { font-size: 13px; color: var(--muted); }
    .progress { margin-top: 10px; height: 8px; border-radius: 99px; background: #e9f0fa; overflow: hidden; border: 1px solid #deebf8; }
    .fill { width: 0; height: 100%; border-radius: 99px; background: linear-gradient(90deg, #2c7bff 0%, #30a7ff 100%); transition: width 260ms ease; }
    .range-row { margin-top: 6px; display: flex; justify-content: space-between; font-size: 11px; color: #7f93ab; }
    .gauge-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
    .gauge-card { border: 1px solid var(--line); border-radius: 10px; padding: 10px; background: #f9fbff; }
    .gauge-title { font-size: 12px; color: var(--muted); margin-bottom: 8px; }
    .gauge-wrap { display: flex; justify-content: center; }
    .gauge {
      width: 148px; height: 148px; border-radius: 50%;
      background: conic-gradient(var(--blue) 0deg, var(--blue) 0deg, #e6eef9 0deg 360deg);
      display: grid; place-items: center; position: relative;
    }
    .gauge::before {
      content: ""; position: absolute; inset: 16px; background: #fff; border-radius: 50%;
      border: 1px solid #ebf1fa;
    }
    .gauge-center { position: relative; z-index: 2; text-align: center; }
    .gauge-center strong { display: block; font-size: 30px; color: var(--title); line-height: 1; }
    .gauge-center span { font-size: 11px; color: var(--muted); }
    .body-grid { display: grid; grid-template-columns: 1.6fr 1fr; gap: 10px; }
    .panel-title { margin: 0 0 8px; font-size: 14px; font-weight: 700; color: var(--title); }
    .chart-wrap { border: 1px solid var(--line); border-radius: 10px; background: #f9fbff; padding: 10px; min-height: 300px; }
    canvas { width: 100%; height: 280px; display: block; }
    .legend { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; }
    .legend span { display: inline-flex; gap: 6px; align-items: center; border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; font-size: 12px; color: #46607f; background: #fff; }
    .legend i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .kpi-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .kpi { border: 1px solid var(--line); border-radius: 10px; padding: 10px; background: #fcfdff; }
    .kpi label { display: block; font-size: 12px; color: var(--muted); }
    .kpi strong { display: block; margin-top: 4px; font-size: 24px; color: var(--title); }
    .threshold-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 6px; }
    .field { border: 1px solid var(--line); border-radius: 8px; background: #fbfdff; padding: 7px; }
    .field label { display: block; font-size: 11px; color: var(--muted); margin-bottom: 4px; }
    .field input { width: 100%; border: 1px solid #d4e1f3; border-radius: 6px; padding: 5px 6px; font-size: 12px; }
    .threshold-actions { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; }
    .log-tools { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
    .checks { display: flex; gap: 10px; align-items: center; font-size: 12px; color: var(--muted); }
    button { border: 1px solid var(--line); background: #f7faff; color: #294467; border-radius: 8px; padding: 5px 10px; font-size: 12px; cursor: pointer; }
    button:hover { background: #edf4ff; }
    pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 12px; line-height: 1.55; max-height: 300px; overflow: auto; border: 1px solid var(--line); background: #fbfdff; border-radius: 8px; padding: 10px; color: #273a53; }
    .toast-wrap { position: fixed; right: 12px; bottom: 12px; display: flex; flex-direction: column; gap: 8px; z-index: 9999; }
    .toast { background: #2e3f57; color: #fff; border-radius: 8px; padding: 8px 10px; font-size: 12px; max-width: 300px; border: 1px solid #516685; }
    @media (max-width: 1080px) { .body-grid { grid-template-columns: 1fr; } .threshold-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 720px) { .threshold-grid { grid-template-columns: 1fr; } .kpi-grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="band">
    <h1 class="title">Huawei IoT 实时看板</h1>
      <p class="subtitle">串口数据经云端下发后，页面实时显示设备状态、趋势和超限提醒</p>
      <div class="status-row">
        <span id="chipConn" class="chip warn">WebSocket 连接中</span>
        <span id="chipMsg" class="chip">消息速率: 0 /s</span>
        <span id="chipTime" class="chip">最近更新: --:--:--</span>
        <span id="chipQuality" class="chip">环境等级: --</span>
        <span id="chipAlert" class="chip">告警: 0</span>
      </div>
    </section>

    <section id="alertPanel" class="alert-panel band">
      <div class="alert-title">当前告警</div>
      <ul id="alertList" class="alert-list"></ul>
    </section>

    <section class="band">
      <div class="metrics">
        <div class="metric"><div class="metric-hd"><span>土壤湿度</span><span id="soilState">--</span></div><div class="metric-value"><strong id="soil">-</strong><span class="unit">%</span></div><div class="progress"><div id="soilBar" class="fill"></div></div><div class="range-row"><span>0</span><span>100</span></div></div>
        <div class="metric"><div class="metric-hd"><span>空气湿度</span><span id="humState">--</span></div><div class="metric-value"><strong id="hum">-</strong><span class="unit">%</span></div><div class="progress"><div id="humBar" class="fill"></div></div><div class="range-row"><span>0</span><span>100</span></div></div>
        <div class="metric"><div class="metric-hd"><span>空气温度</span><span id="tempState">--</span></div><div class="metric-value"><strong id="temp">-</strong><span class="unit">°C</span></div><div class="progress"><div id="tempBar" class="fill"></div></div><div class="range-row"><span>0</span><span>50</span></div></div>
        <div class="metric"><div class="metric-hd"><span>CO2 浓度</span><span id="co2State">--</span></div><div class="metric-value"><strong id="co2">-</strong><span class="unit">ppm</span></div><div class="progress"><div id="co2Bar" class="fill"></div></div><div class="range-row"><span>0</span><span>2000</span></div></div>
        <div class="metric"><div class="metric-hd"><span>光照强度</span><span id="lightState">--</span></div><div class="metric-value"><strong id="light">-</strong><span class="unit">lx</span></div><div class="progress"><div id="lightBar" class="fill"></div></div><div class="range-row"><span>0</span><span>2000</span></div></div>
      </div>
    </section>

    <section class="band">
      <h2 class="panel-title">核心仪表</h2>
      <div class="gauge-grid">
        <div class="gauge-card">
          <div class="gauge-title">温度仪表</div>
          <div class="gauge-wrap"><div id="gTemp" class="gauge"><div class="gauge-center"><strong id="gTempValue">-</strong><span>°C</span></div></div></div>
        </div>
        <div class="gauge-card">
          <div class="gauge-title">湿度仪表</div>
          <div class="gauge-wrap"><div id="gHum" class="gauge"><div class="gauge-center"><strong id="gHumValue">-</strong><span>%</span></div></div></div>
        </div>
        <div class="gauge-card">
          <div class="gauge-title">CO2 仪表</div>
          <div class="gauge-wrap"><div id="gCo2" class="gauge"><div class="gauge-center"><strong id="gCo2Value">-</strong><span>ppm</span></div></div></div>
        </div>
      </div>
    </section>

    <section class="body-grid">
      <div class="band">
        <h2 class="panel-title">最近 60 条趋势</h2>
        <div class="chart-wrap">
          <canvas id="trendCanvas" width="980" height="280"></canvas>
          <div class="legend">
            <span><i style="background:var(--orange)"></i>温度</span>
            <span><i style="background:var(--blue)"></i>湿度</span>
            <span><i style="background:var(--red)"></i>CO2</span>
            <span><i style="background:var(--green)"></i>光照</span>
            <span><i style="background:var(--violet)"></i>土壤</span>
          </div>
        </div>
      </div>

      <div class="band">
        <h2 class="panel-title">状态与阈值</h2>
        <div class="kpi-grid">
          <div class="kpi"><label>平均温度</label><strong id="avgTemp">-</strong></div>
          <div class="kpi"><label>平均湿度</label><strong id="avgHum">-</strong></div>
          <div class="kpi"><label>最大 CO2</label><strong id="maxCo2">-</strong></div>
          <div class="kpi"><label>最大光照</label><strong id="maxLight">-</strong></div>
        </div>

        <div class="threshold-grid">
          <div class="field"><label>温度最小 (°C)</label><input id="th_temp_min" type="number" step="1" /></div>
          <div class="field"><label>温度最大 (°C)</label><input id="th_temp_max" type="number" step="1" /></div>
          <div class="field"><label>湿度最小 (%)</label><input id="th_hum_min" type="number" step="1" /></div>
          <div class="field"><label>湿度最大 (%)</label><input id="th_hum_max" type="number" step="1" /></div>
          <div class="field"><label>土壤最小 (%)</label><input id="th_soil_min" type="number" step="1" /></div>
          <div class="field"><label>土壤最大 (%)</label><input id="th_soil_max" type="number" step="1" /></div>
          <div class="field"><label>CO2 最大 (ppm)</label><input id="th_co2_max" type="number" step="10" /></div>
          <div class="field"><label>光照最小 (lx)</label><input id="th_light_min" type="number" step="10" /></div>
          <div class="field"><label>光照最大 (lx)</label><input id="th_light_max" type="number" step="10" /></div>
        </div>
        <div class="threshold-actions">
          <button id="btnSaveThreshold" type="button">保存阈值</button>
          <button id="btnResetThreshold" type="button">恢复默认</button>
        </div>
      </div>
    </section>

    <section class="band">
      <div class="log-tools">
        <h2 class="panel-title" style="margin:0;">消息日志</h2>
        <div class="checks">
          <label><input id="chkStatus" type="checkbox" checked /> 状态</label>
          <label><input id="chkMqtt" type="checkbox" checked /> 数据</label>
          <button id="btnClear" type="button">清空日志</button>
        </div>
      </div>
      <pre id="log"></pre>
    </section>
  </div>
  <div id="toastWrap" class="toast-wrap"></div>

  <script>
    const MAX_POINTS = 60;
    const THRESHOLD_KEY = "iot_thresholds_v1";
    const DEFAULT_THRESHOLD = {
      tempMin: 10, tempMax: 30,
      humMin: 30, humMax: 70,
      soilMin: 20, soilMax: 80,
      co2Max: 1200,
      lightMin: 200, lightMax: 1200,
    };

    const history = { t: [], h: [], c: [], l: [], s: [], ts: [] };
    const logEl = document.getElementById("log");
    const chipConn = document.getElementById("chipConn");
    const chipMsg = document.getElementById("chipMsg");
    const chipTime = document.getElementById("chipTime");
    const chipQuality = document.getElementById("chipQuality");
    const chipAlert = document.getElementById("chipAlert");
    const alertPanel = document.getElementById("alertPanel");
    const alertList = document.getElementById("alertList");
    const toastWrap = document.getElementById("toastWrap");
    const chkStatus = document.getElementById("chkStatus");
    const chkMqtt = document.getElementById("chkMqtt");

    const thresholdInputs = {
      tempMin: document.getElementById("th_temp_min"),
      tempMax: document.getElementById("th_temp_max"),
      humMin: document.getElementById("th_hum_min"),
      humMax: document.getElementById("th_hum_max"),
      soilMin: document.getElementById("th_soil_min"),
      soilMax: document.getElementById("th_soil_max"),
      co2Max: document.getElementById("th_co2_max"),
      lightMin: document.getElementById("th_light_min"),
      lightMax: document.getElementById("th_light_max"),
    };

    const metricMap = {
      soil: { value: document.getElementById("soil"), bar: document.getElementById("soilBar"), state: document.getElementById("soilState"), min: 0, max: 100 },
      hum: { value: document.getElementById("hum"), bar: document.getElementById("humBar"), state: document.getElementById("humState"), min: 0, max: 100 },
      temp: { value: document.getElementById("temp"), bar: document.getElementById("tempBar"), state: document.getElementById("tempState"), min: 0, max: 50 },
      co2: { value: document.getElementById("co2"), bar: document.getElementById("co2Bar"), state: document.getElementById("co2State"), min: 0, max: 2000 },
      light: { value: document.getElementById("light"), bar: document.getElementById("lightBar"), state: document.getElementById("lightState"), min: 0, max: 2000 },
    };

    const gauges = {
      temp: { el: document.getElementById("gTemp"), val: document.getElementById("gTempValue"), min: 0, max: 50, color: "#f97316" },
      hum: { el: document.getElementById("gHum"), val: document.getElementById("gHumValue"), min: 0, max: 100, color: "#2b82ff" },
      co2: { el: document.getElementById("gCo2"), val: document.getElementById("gCo2Value"), min: 0, max: 2000, color: "#ef4444" },
    };

    const avgTempEl = document.getElementById("avgTemp");
    const avgHumEl = document.getElementById("avgHum");
    const maxCo2El = document.getElementById("maxCo2");
    const maxLightEl = document.getElementById("maxLight");
    const canvas = document.getElementById("trendCanvas");
    const ctx = canvas.getContext("2d");
    const msgTicks = [];
    let thresholds = { ...DEFAULT_THRESHOLD };
    let lastAlertSignature = "";
    let alertToneLock = false;

    function asNumber(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }
    function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }
    function average(arr) { const valid = arr.filter((v) => v != null); return valid.length ? valid.reduce((a, b) => a + b, 0) / valid.length : null; }
    function maxValue(arr) { const valid = arr.filter((v) => v != null); return valid.length ? Math.max(...valid) : null; }

    function showToast(msg) {
      const item = document.createElement("div");
      item.className = "toast";
      item.textContent = msg;
      toastWrap.appendChild(item);
      setTimeout(() => item.remove(), 4500);
    }

    function beep() {
      if (alertToneLock) return;
      alertToneLock = true;
      try {
        const ac = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ac.createOscillator();
        const gain = ac.createGain();
        osc.connect(gain); gain.connect(ac.destination);
        osc.type = "sine"; osc.frequency.value = 880;
        gain.gain.setValueAtTime(0.001, ac.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.08, ac.currentTime + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + 0.24);
        osc.start(); osc.stop(ac.currentTime + 0.25);
      } catch (e) {}
      setTimeout(() => { alertToneLock = false; }, 1200);
    }

    function levelText(key, value) {
      if (value == null) return "--";
      if (key === "temp") return value <= 10 ? "偏低" : value <= 30 ? "正常" : "偏高";
      if (key === "hum") return value < 30 ? "偏低" : value <= 70 ? "正常" : "偏高";
      if (key === "soil") return value < 20 ? "偏干" : value <= 80 ? "正常" : "偏湿";
      if (key === "co2") return value < 800 ? "优" : value <= 1200 ? "一般" : "偏高";
      if (key === "light") return value < 200 ? "偏暗" : value <= 1000 ? "适中" : "较强";
      return "--";
    }

    function levelClass(key, value) {
      if (value == null) return "warn";
      if (key === "co2") return value <= 1200 ? "ok" : "bad";
      if (key === "temp") return value >= 10 && value <= 30 ? "ok" : "warn";
      if (key === "hum") return value >= 30 && value <= 70 ? "ok" : "warn";
      if (key === "soil") return value >= 20 && value <= 80 ? "ok" : "warn";
      if (key === "light") return value >= 200 && value <= 1200 ? "ok" : "warn";
      return "warn";
    }

    function updateMetric(key, raw) {
      const cfg = metricMap[key];
      const value = asNumber(raw);
      cfg.value.textContent = value == null ? "-" : String(value);
      cfg.state.textContent = levelText(key, value);
      cfg.state.style.color = levelClass(key, value) === "ok" ? "#15825c" : (levelClass(key, value) === "bad" ? "#bf2f33" : "#9a6a00");
      const pct = value == null ? 0 : (100 * (value - cfg.min) / (cfg.max - cfg.min));
      cfg.bar.style.width = `${clamp(pct, 0, 100)}%`;
    }

    function updateGauge(name, raw) {
      const g = gauges[name];
      const value = asNumber(raw);
      g.val.textContent = value == null ? "-" : String(value);
      const pct = value == null ? 0 : clamp((value - g.min) / (g.max - g.min), 0, 1);
      const deg = Math.round(pct * 360);
      g.el.style.background = `conic-gradient(${g.color} 0deg, ${g.color} ${deg}deg, #e6eef9 ${deg}deg 360deg)`;
    }

    function pushHistory(d) {
      const t = asNumber(d.CurrentTemperature), h = asNumber(d.CurrentHumidity), c = asNumber(d.co2), l = asNumber(d.LightLux), s = asNumber(d.SoilMoisture);
      history.t.push(t); history.h.push(h); history.c.push(c); history.l.push(l); history.s.push(s); history.ts.push(new Date());
      Object.keys(history).forEach((k) => { if (history[k].length > MAX_POINTS) history[k].shift(); });
    }

    function drawLine(values, maxV, color) {
      if (!values.length) return;
      const w = canvas.width, h = canvas.height, left = 40, right = 12, top = 16, bottom = h - 16;
      const usableW = w - left - right, usableH = bottom - top, steps = Math.max(values.length - 1, 1);
      ctx.beginPath();
      values.forEach((v, i) => {
        if (v == null) return;
        const x = left + (i / steps) * usableW;
        const y = top + (1 - clamp(v / maxV, 0, 1)) * usableH;
        if (i === 0 || values[i - 1] == null) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
    }

    function drawTrend() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#f9fbff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.strokeStyle = "#dfe9f8";
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = 16 + i * ((canvas.height - 32) / 4);
        ctx.beginPath(); ctx.moveTo(40, y); ctx.lineTo(canvas.width - 12, y); ctx.stroke();
      }
      drawLine(history.t, 50, "#f97316");
      drawLine(history.h, 100, "#2b82ff");
      drawLine(history.c, 2000, "#ef4444");
      drawLine(history.l, 2000, "#22a06b");
      drawLine(history.s, 100, "#8b5cf6");
    }

    function updateSummary() {
      const avgT = average(history.t), avgH = average(history.h), maxC = maxValue(history.c), maxL = maxValue(history.l);
      avgTempEl.textContent = avgT == null ? "-" : `${avgT.toFixed(1)} °C`;
      avgHumEl.textContent = avgH == null ? "-" : `${avgH.toFixed(1)} %`;
      maxCo2El.textContent = maxC == null ? "-" : `${maxC} ppm`;
      maxLightEl.textContent = maxL == null ? "-" : `${maxL} lx`;
    }

    function updateQualityTag(d) {
      const t = asNumber(d.CurrentTemperature), h = asNumber(d.CurrentHumidity), c = asNumber(d.co2);
      let score = 100;
      if (t != null && (t < thresholds.tempMin || t > thresholds.tempMax)) score -= 20;
      if (h != null && (h < thresholds.humMin || h > thresholds.humMax)) score -= 20;
      if (c != null && c > thresholds.co2Max) score -= 35;
      const quality = score >= 85 ? "优" : score >= 60 ? "一般" : "需关注";
      chipQuality.textContent = `环境等级: ${quality} (${score})`;
      chipQuality.className = `chip ${score >= 85 ? "ok" : score >= 60 ? "warn" : "bad"}`;
    }

    function writeLog(type, obj) {
      if (type === "status" && !chkStatus.checked) return;
      if (type === "mqtt" && !chkMqtt.checked) return;
      const line = `[${new Date().toLocaleTimeString()}] ${JSON.stringify(obj)}`;
      logEl.textContent = `${line}\n${logEl.textContent}`.slice(0, 40000);
    }

    function normalizePayload(p) {
      const source = p && typeof p === "object" ? p : {};
      const params = source.params && typeof source.params === "object"
        ? source.params
        : source.data && typeof source.data === "object"
          ? source.data
          : source.items && typeof source.items === "object"
            ? source.items
            : source;
      return {
        SoilMoisture: params.SoilMoisture ?? params.soil,
        CurrentHumidity: params.CurrentHumidity ?? (params.air1 ? params.air1.h : undefined),
        CurrentTemperature: params.CurrentTemperature ?? (params.air1 ? params.air1.t : undefined),
        co2: params.co2,
        LightLux: params.LightLux ?? params.light,
      };
    }

    function evaluateAlerts(d) {
      const list = [];
      const t = asNumber(d.CurrentTemperature);
      const h = asNumber(d.CurrentHumidity);
      const s = asNumber(d.SoilMoisture);
      const c = asNumber(d.co2);
      const l = asNumber(d.LightLux);

      if (t != null && t < thresholds.tempMin) list.push(`温度过低: ${t} < ${thresholds.tempMin}`);
      if (t != null && t > thresholds.tempMax) list.push(`温度过高: ${t} > ${thresholds.tempMax}`);
      if (h != null && h < thresholds.humMin) list.push(`湿度过低: ${h} < ${thresholds.humMin}`);
      if (h != null && h > thresholds.humMax) list.push(`湿度过高: ${h} > ${thresholds.humMax}`);
      if (s != null && s < thresholds.soilMin) list.push(`土壤湿度过低: ${s} < ${thresholds.soilMin}`);
      if (s != null && s > thresholds.soilMax) list.push(`土壤湿度过高: ${s} > ${thresholds.soilMax}`);
      if (c != null && c > thresholds.co2Max) list.push(`CO2 过高: ${c} > ${thresholds.co2Max}`);
      if (l != null && l < thresholds.lightMin) list.push(`光照过低: ${l} < ${thresholds.lightMin}`);
      if (l != null && l > thresholds.lightMax) list.push(`光照过高: ${l} > ${thresholds.lightMax}`);
      return list;
    }

    function renderAlerts(alerts) {
      chipAlert.textContent = `告警: ${alerts.length}`;
      chipAlert.className = alerts.length ? "chip bad" : "chip ok";
      alertList.innerHTML = "";
      if (!alerts.length) {
        alertPanel.style.display = "none";
        return;
      }
      alertPanel.style.display = "block";
      alerts.forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        alertList.appendChild(li);
      });

      const signature = alerts.join("|");
      if (signature !== lastAlertSignature) {
        showToast(`参数超限: ${alerts[0]}`);
        beep();
        lastAlertSignature = signature;
      }
    }

    function applyThresholdToInputs() {
      Object.keys(thresholdInputs).forEach((k) => {
        thresholdInputs[k].value = String(thresholds[k]);
      });
    }

    function readThresholdFromInputs() {
      const next = { ...thresholds };
      Object.keys(thresholdInputs).forEach((k) => {
        const v = asNumber(thresholdInputs[k].value);
        if (v != null) next[k] = v;
      });
      thresholds = next;
      localStorage.setItem(THRESHOLD_KEY, JSON.stringify(thresholds));
      showToast("阈值已保存");
    }

    function loadThreshold() {
      try {
        const raw = localStorage.getItem(THRESHOLD_KEY);
        if (!raw) return;
        const obj = JSON.parse(raw);
        if (obj && typeof obj === "object") thresholds = { ...thresholds, ...obj };
      } catch (e) {}
    }

    function applyData(d) {
      updateMetric("soil", d.SoilMoisture);
      updateMetric("hum", d.CurrentHumidity);
      updateMetric("temp", d.CurrentTemperature);
      updateMetric("co2", d.co2);
      updateMetric("light", d.LightLux);
      updateGauge("temp", d.CurrentTemperature);
      updateGauge("hum", d.CurrentHumidity);
      updateGauge("co2", d.co2);
      pushHistory(d);
      drawTrend();
      updateSummary();
      updateQualityTag(d);
      renderAlerts(evaluateAlerts(d));
      chipTime.textContent = `最近更新: ${new Date().toLocaleTimeString()}`;
    }

    function tickMsgRate() {
      const now = Date.now();
      while (msgTicks.length && now - msgTicks[0] > 1000) msgTicks.shift();
      chipMsg.textContent = `消息速率: ${msgTicks.length} /s`;
    }

    document.getElementById("btnClear").addEventListener("click", () => { logEl.textContent = ""; });
    document.getElementById("btnSaveThreshold").addEventListener("click", readThresholdFromInputs);
    document.getElementById("btnResetThreshold").addEventListener("click", () => {
      thresholds = { ...DEFAULT_THRESHOLD };
      localStorage.removeItem(THRESHOLD_KEY);
      applyThresholdToInputs();
      showToast("已恢复默认阈值");
    });

    loadThreshold();
    applyThresholdToInputs();
    setInterval(tickMsgRate, 300);
    drawTrend();

    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${wsProto}://${location.host}/ws`);
    ws.onopen = () => { chipConn.textContent = "WebSocket 已连接"; chipConn.className = "chip ok"; };
    ws.onclose = () => { chipConn.textContent = "WebSocket 已断开"; chipConn.className = "chip bad"; };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      msgTicks.push(Date.now());
      if (msg.type === "latest" && msg.data) applyData(msg.data);
      else if (msg.type === "mqtt" && msg.payload) applyData(normalizePayload(msg.payload));
      writeLog(msg.type, msg);
    };
  </script>
</body>
</html>
""".strip()


@app.get("/")
async def index():
    if not dashboard_access_enabled():
        return HTMLResponse(
            "<h3>Dashboard access disabled from QT / 看板访问已关闭</h3>",
            status_code=503,
        )
    return HTMLResponse(DASHBOARD_HTML)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not dashboard_access_enabled():
        await ws.close(code=1013)
        return

    await hub.connect(ws)
    try:
        while True:
            if not dashboard_access_enabled():
                await ws.close(code=1013)
                hub.disconnect(ws)
                break
            try:
                # Browser usually sends none; timeout lets us check access switch.
                await asyncio.wait_for(ws.receive_text(), timeout=1.5)
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        hub.disconnect(ws)
    except Exception:
        hub.disconnect(ws)


if __name__ == "__main__":
    import uvicorn

    web_host = _env("WEB_HOST", "0.0.0.0")
    try:
        web_port = int(_env("WEB_PORT", "8000"))
    except Exception:
        web_port = 8000

    print(f"[WEB] Dashboard Local URL: http://127.0.0.1:{web_port}", flush=True)
    lan_ips = detect_lan_ipv4s()
    if web_host in {"0.0.0.0", "::"}:
        if lan_ips:
            for ip in lan_ips:
                print(f"[WEB] Dashboard LAN URL  : http://{ip}:{web_port}", flush=True)
        else:
            print("[WEB] Dashboard LAN URL  : (No private IPv4 detected)", flush=True)
    else:
        print(f"[WEB] Dashboard Bind Host : {web_host}", flush=True)

    uvicorn.run(app, host=web_host, port=web_port, reload=False)
