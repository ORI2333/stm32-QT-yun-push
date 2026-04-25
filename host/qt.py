# -*- coding: utf-8 -*-
import hashlib
import hmac
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
from io import BytesIO
from copy import deepcopy

import paho.mqtt.client as mqtt
import serial
import serial.tools.list_ports
from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
	QApplication,
	QCheckBox,
	QComboBox,
	QFormLayout,
	QGridLayout,
	QGroupBox,
	QHBoxLayout,
	QLabel,
	QLineEdit,
	QMainWindow,
	QMessageBox,
	QPushButton,
	QTextEdit,
	QVBoxLayout,
	QWidget,
)

try:
	import qrcode

	HAS_QRCODE = True
except Exception:
	qrcode = None
	HAS_QRCODE = False


# Edit this block only when you want to change default values.
APP_CONFIG = {
	"window": {
		"title": "Serial -> Huawei IoTDA Host",
		"width": 1100,
		"height": 760,
	},
	"serial": {
		"baud_rates": ["9600", "115200", "230400", "460800"],
		"default_baud": "115200",
	},
	
	"cloud": {
		"product_key": "a17MwdB5xAq",
		"device_name": "your_device_id",
		"device_secret": "your_device_secret",
		"platform": "huawei",
		"mqtt_host": "your-instance.st1.iotda-device.cn-east-3.myhuaweicloud.com",
		"mqtt_port": 8883,
		"mqtt_tls": True,
		"mqtt_username": "",
		"mqtt_password": "",
		"mqtt_client_id": "",
		"service_id": "env_monitor",
		"regions": ["cn-east-3", "cn-shanghai", "cn-beijing", "cn-shenzhen", "cn-hangzhou"],
		"default_region": "cn-east-3",
	},
	"behavior": {
		"auto_upload": True,
		"show_secret": False,
		"pnp_scan_timeout_sec": 5,
		"local_relay_enable": True,
		"local_relay_host": "127.0.0.1",
		"local_relay_port": 19091,
		"default_language": "zh",
		"web_host_default": "0.0.0.0",
		"web_port_default": 8000,
	},
}


def get_runtime_base_dir():
	if getattr(sys, "frozen", False):
		return os.path.dirname(os.path.abspath(sys.executable))
	return os.path.dirname(os.path.abspath(__file__))


def detect_lan_ipv4s():
	ips = set()

	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		try:
			sock.connect(("8.8.8.8", 80))
			ips.add(sock.getsockname()[0])
		finally:
			sock.close()
	except Exception:
		pass

	try:
		host = socket.gethostname()
		for item in socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM):
			ip = item[4][0]
			if ip:
				ips.add(ip)
	except Exception:
		pass

	def _usable(ip):
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


class SerialReaderThread(QThread):
	line_received = pyqtSignal(str)
	error = pyqtSignal(str)
	status = pyqtSignal(bool, str)

	def __init__(self):
		super().__init__()
		self._serial = None
		self._running = False

	def open_port(self, port, baudrate):
		if self._serial and self._serial.is_open:
			self.close_port()

		try:
			self._serial = serial.Serial(port=port, baudrate=baudrate, timeout=0.2)
			self._running = True
			if not self.isRunning():
				self.start()
			self.status.emit(True, f"Serial opened: {port} @ {baudrate}")
		except Exception as exc:
			self.error.emit(f"Open serial failed: {exc}")

	def close_port(self):
		self._running = False
		if self._serial:
			try:
				if self._serial.is_open:
					self._serial.close()
			except Exception:
				pass
			self._serial = None
		self.status.emit(False, "Serial closed")

	def run(self):
		while True:
			if not self._running or not self._serial:
				self.msleep(100)
				continue

			try:
				raw = self._serial.readline()
				if not raw:
					continue
				line = raw.decode("utf-8", errors="ignore").strip()
				if line:
					self.line_received.emit(line)
			except Exception as exc:
				self.error.emit(f"Serial read error: {exc}")
				self.close_port()


class AliyunMqttClient:
	def __init__(self, log_callback, connect_callback, message_callback):
		self._client = None
		self._connected = False
		self._log = log_callback
		self._on_connect_status = connect_callback
		self._on_message = message_callback

		self.product_key = ""
		self.device_name = ""
		self.device_secret = ""
		self.platform = "huawei"
		self.mqtt_host = ""
		self.mqtt_port = 1883
		self.mqtt_tls = False
		self.mqtt_username = ""
		self.mqtt_password = ""
		self.mqtt_client_id = ""
		self.service_id = "env_monitor"
		self.region = "cn-shanghai"

	@property
	def connected(self):
		return self._connected

	@staticmethod
	def _build_auth(product_key, device_name, device_secret):
		timestamp = str(int(time.time() * 1000))
		client_id = f"{device_name}_pc"
		sign_content = (
			f"clientId{client_id}"
			f"deviceName{device_name}"
			f"productKey{product_key}"
			f"timestamp{timestamp}"
		)
		password = hmac.new(
			device_secret.encode("utf-8"),
			sign_content.encode("utf-8"),
			digestmod=hashlib.sha256,
		).hexdigest()

		mqtt_client_id = (
			f"{client_id}|securemode=2,signmethod=hmacsha256,timestamp={timestamp}|"
		)
		username = f"{device_name}&{product_key}"
		return mqtt_client_id, username, password

	@staticmethod
	def _build_huawei_auth(device_id, device_secret):
		# Huawei IoTDA MQTT key-auth requires UTC hour timestamp: YYYYMMDDHH.
		timestamp = time.strftime("%Y%m%d%H", time.gmtime())
		client_id = f"{device_id}_0_0_{timestamp}"
		username = device_id
		password = hmac.new(
			device_secret.encode("utf-8"),
			timestamp.encode("utf-8"),
			digestmod=hashlib.sha256,
		).hexdigest()
		return client_id, username, password

	def connect(
		self,
		product_key,
		device_name,
		device_secret,
		region="cn-shanghai",
		platform="huawei",
		mqtt_host="",
		mqtt_port=1883,
		mqtt_tls=False,
		mqtt_username="",
		mqtt_password="",
		mqtt_client_id="",
		service_id="env_monitor",
	):
		if self._connected:
			self.disconnect()

		self.product_key = product_key.strip()
		self.device_name = device_name.strip()
		self.device_secret = device_secret.strip()
		self.region = region.strip()
		self.platform = str(platform or "huawei").strip().lower()
		self.mqtt_host = str(mqtt_host or "").strip()
		self.mqtt_port = int(mqtt_port or 1883)
		self.mqtt_tls = bool(mqtt_tls)
		self.mqtt_username = str(mqtt_username or "").strip()
		self.mqtt_password = str(mqtt_password or "").strip()
		self.mqtt_client_id = str(mqtt_client_id or "").strip()
		self.service_id = str(service_id or "env_monitor").strip() or "env_monitor"

		if self.platform == "huawei":
			has_manual = bool(self.mqtt_username and self.mqtt_password and self.mqtt_client_id)
			has_auto = bool(self.device_name and self.device_secret)
			if not (has_manual or has_auto):
				self._log(
					"Cloud auth fields cannot be empty: "
					"need HUAWEI_MQTT_USERNAME/PASSWORD/CLIENT_ID or DEVICE_NAME/DEVICE_SECRET"
				)
				self._on_connect_status(False, "Cloud auth missing")
				return
			if not self.mqtt_host:
				self._on_connect_status(False, "Cloud connect failed")
				self._log("Cloud connect failed: missing cloud.mqtt_host for Huawei IoTDA")
				return
			host = self.mqtt_host
			port = self.mqtt_port
			if has_manual:
				client_id = self.mqtt_client_id
				username = self.mqtt_username
				password = self.mqtt_password
			else:
				client_id, username, password = self._build_huawei_auth(
					self.device_name, self.device_secret
				)
		else:
			if not (self.product_key and self.device_name and self.device_secret and self.region):
				self._log("Cloud auth fields cannot be empty")
				self._on_connect_status(False, "Cloud auth missing")
				return
			host = f"{self.product_key}.iot-as-mqtt.{self.region}.aliyuncs.com"
			port = 1883
			client_id, username, password = self._build_auth(
				self.product_key, self.device_name, self.device_secret
			)

		self._client = mqtt.Client(client_id=client_id, clean_session=True)
		self._client.username_pw_set(username=username, password=password)
		self._client.on_connect = self._handle_connect
		self._client.on_disconnect = self._handle_disconnect
		self._client.on_message = self._handle_message
		if self.platform == "huawei" and (self.mqtt_tls or int(port) == 8883):
			self._client.tls_set()

		try:
			self._client.connect(host, port=port, keepalive=60)
			self._client.loop_start()
			self._log(f"Connecting Cloud MQTT: {host}:{port}")
		except Exception as exc:
			self._connected = False
			self._on_connect_status(False, "Cloud connect failed")
			self._log(f"Cloud connect failed: {exc}")

	def disconnect(self):
		if self._client:
			try:
				self._client.loop_stop()
				self._client.disconnect()
			except Exception:
				pass
		self._client = None
		self._connected = False
		self._on_connect_status(False, "Cloud disconnected")

	def publish_properties(self, params):
		if not self._connected or not self._client:
			self._log("Skip publish: Cloud not connected")
			return

		if self.platform == "huawei":
			topic = f"$oc/devices/{self.device_name}/sys/properties/report"
			properties = {
				"soil_moisture": params.get("SoilMoisture"),
				"current_humidity": params.get("CurrentHumidity"),
				"current_temperature": params.get("CurrentTemperature"),
				"co2": params.get("co2"),
				"light_lux": params.get("LightLux"),
			}
			properties = {k: v for k, v in properties.items() if v is not None}
			payload = {
				"services": [
					{
						"service_id": self.service_id,
						"properties": properties,
					}
				]
			}
		else:
			topic = (
				f"/sys/{self.product_key}/{self.device_name}/thing/event/property/post"
			)
			payload = {
				"id": str(int(time.time() * 1000)),
				"version": "1.0",
				"method": "thing.event.property.post",
				"params": params,
			}

		try:
			result = self._client.publish(topic, json.dumps(payload), qos=1)
			self._log(
				f"Publish property: rc={result.rc}, topic={topic}, params={json.dumps(params)}"
			)
		except Exception as exc:
			self._log(f"Publish failed: {exc}")

	def _handle_connect(self, client, userdata, flags, rc):
		if rc == 0:
			self._connected = True
			self._on_connect_status(True, "Cloud connected")
			if self.platform == "huawei":
				# Subscribe broad system topics for diagnostics and command downlink.
				down_topics = [
					f"$oc/devices/{self.device_name}/sys/#",
				]
				for t in down_topics:
					client.subscribe(t, qos=1)
					self._log(f"Subscribed: {t}")
			else:
				reply_topic = (
					f"/sys/{self.product_key}/{self.device_name}/thing/event/property/post_reply"
				)
				client.subscribe(reply_topic, qos=1)
				self._log(f"Subscribed: {reply_topic}")
		else:
			self._connected = False
			self._on_connect_status(False, f"Cloud connect rc={rc}")
			self._log(f"Cloud MQTT connect rejected, rc={rc}")

	def _handle_disconnect(self, client, userdata, rc):
		self._connected = False
		self._on_connect_status(False, f"Cloud disconnected rc={rc}")

	def _handle_message(self, client, userdata, msg):
		payload = msg.payload.decode("utf-8", errors="ignore")
		self._on_message(msg.topic, payload)


class MainWindow(QMainWindow):
	log_signal = pyqtSignal(str)
	mqtt_status_signal = pyqtSignal(bool, str)
	mqtt_message_signal = pyqtSignal(str, str)
	I18N = {
		"zh": {
			"window_title": "串口 -> 华为云 IoTDA 主机",
			"group_serial": "串口",
			"group_aliyun": "华为云 IoTDA",
			"group_data": "串口监听的实时数据",
			"group_log": "日志",
			"group_access": "订阅云端消息本地 Web 访问地址",
			"label_port": "端口",
			"label_baud": "波特率",
			"label_status": "状态",
			"btn_refresh": "刷新",
			"btn_open": "打开",
			"btn_close": "关闭",
			"label_product_key": "ProductKey",
			"label_device_name": "DeviceName",
			"label_device_secret": "DeviceSecret",
			"label_region": "地域",
			"btn_connect": "连接",
			"btn_disconnect": "断开",
			"show_secret": "显示密钥",
			"auto_upload": "串口接收后自动上报",
			"last_raw_json": "最近一条原始 JSON",
			"btn_manual_publish": "手动上报最新数据",
			"label_language": "语言",
			"label_dashboard_urls": "Web 看板访问地址",
			"btn_refresh_urls": "刷新地址",
			"group_webcfg": "Web 配置（写入 .env）",
			"label_web_backend_mode": "后端模式",
			"label_web_product_key": "Web ProductKey",
			"label_web_region": "Web Region",
			"label_web_consumer_group_id": "AMQP Queue",
			"label_web_access_key_id": "AMQP AccessKey",
			"label_web_access_key_secret": "AMQP AccessCode",
			"label_web_amqp_endpoint": "AMQP Endpoint",
			"label_web_amqp_instance_id": "AMQP InstanceId",
			"label_web_device_name": "Web DeviceName",
			"label_web_device_secret": "Web DeviceSecret",
			"label_web_mqtt_host": "Hua MQTT Host",
			"label_web_mqtt_port": "Hua MQTT Port",
			"label_web_mqtt_tls": "Hua MQTT TLS",
			"label_web_mqtt_username": "Hua MQTT User",
			"label_web_mqtt_password": "Hua MQTT Pass",
			"label_web_mqtt_client_id": "Hua MQTT ClientId",
			"label_web_host": "WEB_HOST",
			"label_web_port": "WEB_PORT",
			"show_web_secret": "显示 Web 密钥",
			"btn_load_web_cfg": "加载 .env",
			"btn_save_web_cfg": "保存 .env",
			"label_dashboard_proc": "看板进程",
			"label_dashboard_qr": "访问二维码",
			"dashboard_running": "已开启",
			"dashboard_stopped": "已关闭",
			"btn_start_dashboard": "开启访问",
			"btn_stop_dashboard": "关闭访问",
			"msg_dashboard_starting": "已开启看板访问",
			"msg_dashboard_stopping": "已关闭看板访问，页面将无法加载",
			"msg_dashboard_not_found": "未找到 web_dashboard.py",
			"msg_dashboard_exited": "Web 看板已退出",
			"msg_qr_dep_missing": "未安装 qrcode 依赖，无法生成二维码",
			"msg_qr_none": "暂无二维码",
			"url_disabled": "看板访问已关闭（Web 将返回 503）",
			"label_dashboard_proc": "看板访问",
			"backend_local_relay": "仅本地转发（同设备推荐）",
			"backend_amqp": "AMQP（云端拉取）",
			"backend_mqtt_ws": "MQTT(S)",
			"msg_web_cfg_loaded": "已从 .env 加载 Web 配置",
			"msg_web_cfg_saved": "Web 配置已保存到 .env。重启 web_dashboard.py 后生效。",
			"msg_web_cfg_save_failed": "保存 .env 失败",
			"lang_zh": "中文",
			"lang_en": "English",
			"disconnected": "未连接",
			"msg_no_port": "请选择串口",
			"msg_no_data": "暂无可上报的解析数据",
			"warning": "警告",
			"info": "提示",
			"url_local": "本机",
			"url_lan": "局域网",
			"url_none": "未检测到可用局域网 IPv4，请检查网卡连接。",
		},
		"en": {
			"window_title": "Serial -> Huawei IoTDA Host",
			"group_serial": "Serial",
			"group_aliyun": "Huawei IoTDA",
			"group_data": "Realtime Data",
			"group_log": "Log",
			"group_access": "Access & Language",
			"label_port": "Port",
			"label_baud": "Baud",
			"label_status": "Status",
			"btn_refresh": "Refresh",
			"btn_open": "Open",
			"btn_close": "Close",
			"label_product_key": "ProductKey",
			"label_device_name": "DeviceName",
			"label_device_secret": "DeviceSecret",
			"label_region": "Region",
			"btn_connect": "Connect",
			"btn_disconnect": "Disconnect",
			"show_secret": "Show Secret",
			"auto_upload": "Auto upload on serial receive",
			"last_raw_json": "Last Raw JSON",
			"btn_manual_publish": "Manual Publish Latest",
			"label_language": "Language",
			"label_dashboard_urls": "Web Dashboard URLs",
			"btn_refresh_urls": "Refresh URLs",
			"group_webcfg": "Web Config (write to .env)",
			"label_web_backend_mode": "Backend Mode",
			"label_web_product_key": "Web ProductKey",
			"label_web_region": "Web Region",
			"label_web_consumer_group_id": "AMQP Queue",
			"label_web_access_key_id": "AMQP AccessKey",
			"label_web_access_key_secret": "AMQP AccessCode",
			"label_web_amqp_endpoint": "AMQP Endpoint",
			"label_web_amqp_instance_id": "AMQP InstanceId",
			"label_web_device_name": "Web DeviceName",
			"label_web_device_secret": "Web DeviceSecret",
			"label_web_mqtt_host": "Hua MQTT Host",
			"label_web_mqtt_port": "Hua MQTT Port",
			"label_web_mqtt_tls": "Hua MQTT TLS",
			"label_web_mqtt_username": "Hua MQTT User",
			"label_web_mqtt_password": "Hua MQTT Pass",
			"label_web_mqtt_client_id": "Hua MQTT ClientId",
			"label_web_host": "WEB_HOST",
			"label_web_port": "WEB_PORT",
			"show_web_secret": "Show Web Secrets",
			"btn_load_web_cfg": "Load .env",
			"btn_save_web_cfg": "Save .env",
			"label_dashboard_proc": "Dashboard Access",
			"label_dashboard_qr": "QR URL",
			"dashboard_running": "Enabled",
			"dashboard_stopped": "Disabled",
			"btn_start_dashboard": "Enable Access",
			"btn_stop_dashboard": "Disable Access",
			"msg_dashboard_starting": "Dashboard access enabled",
			"msg_dashboard_stopping": "Dashboard access disabled (page will not load)",
			"msg_dashboard_not_found": "web_dashboard.py not found",
			"msg_dashboard_exited": "Web dashboard exited",
			"msg_qr_dep_missing": "qrcode dependency not installed",
			"msg_qr_none": "No QR available",
			"url_disabled": "Dashboard access is disabled (Web returns 503)",
			"backend_local_relay": "Local Relay Only (Recommended)",
			"backend_amqp": "AMQP (Cloud Pull)",
			"backend_mqtt_ws": "MQTT(S)",
			"msg_web_cfg_loaded": "Web config loaded from .env",
			"msg_web_cfg_saved": "Web config saved to .env. Restart web_dashboard.py to apply.",
			"msg_web_cfg_save_failed": "Failed to save .env",
			"lang_zh": "中文",
			"lang_en": "English",
			"disconnected": "Disconnected",
			"msg_no_port": "Please select serial port",
			"msg_no_data": "No parsed sensor data yet",
			"warning": "Warning",
			"info": "Info",
			"url_local": "Local",
			"url_lan": "LAN",
			"url_none": "No available LAN IPv4 detected. Please check network connection.",
		},
	}

	def __init__(self):
		super().__init__()
		self.config = deepcopy(APP_CONFIG)
		default_lang = self.config.get("behavior", {}).get("default_language", "zh")
		self.lang = default_lang if default_lang in self.I18N else "zh"
		self.setWindowTitle(self.tr("window_title"))
		self.resize(self.config["window"]["width"], self.config["window"]["height"])

		self.latest_params = {}
		self._relay_error_logged = False
		self._last_serial_status_raw = ""
		self._last_mqtt_status_raw = ""
		self.runtime_base_dir = get_runtime_base_dir()
		self.web_env_path = os.path.join(self.runtime_base_dir, ".env")
		self.web_script_path = os.path.join(self.runtime_base_dir, "web_dashboard.py")
		self.dashboard_access_flag_path = os.path.join(
			self.runtime_base_dir, ".dashboard_access"
		)
		self.dashboard_access_enabled = True
		self.log_signal.connect(self._append_log)
		self.mqtt_status_signal.connect(self.on_mqtt_status)
		self.mqtt_message_signal.connect(self.on_mqtt_message)

		self.serial_thread = SerialReaderThread()
		self.serial_thread.line_received.connect(self.on_serial_line)
		self.serial_thread.error.connect(self.log)
		self.serial_thread.status.connect(self.on_serial_status)

		self.aliyun = AliyunMqttClient(
			log_callback=lambda text: self.log_signal.emit(str(text)),
			connect_callback=lambda ok, text: self.mqtt_status_signal.emit(ok, str(text)),
			message_callback=lambda topic, payload: self.mqtt_message_signal.emit(
				str(topic), str(payload)
			),
		)

		self._build_ui()
		self._apply_theme()
		self.load_web_config_from_file(log=False, notify=False)
		self.refresh_ports()
		self._sync_dashboard_access_from_flag(default=True, log=False)
		self.refresh_dashboard_urls()
		self.apply_language(refresh_status_text=False)
		self.dashboard_access_watchdog = QTimer(self)
		self.dashboard_access_watchdog.setInterval(1200)
		self.dashboard_access_watchdog.timeout.connect(self._check_web_process_status)
		self.dashboard_access_watchdog.start()

	def tr(self, key):
		return self.I18N.get(self.lang, self.I18N["en"]).get(key, key)

	def translate_runtime_text(self, text):
		mapping = [
			("Serial opened:", "串口已打开:", "Serial opened:"),
			("Serial closed", "串口已关闭", "Serial closed"),
			("Open serial failed:", "打开串口失败:", "Open serial failed:"),
			("Serial read error:", "串口读取错误:", "Serial read error:"),
			("Cloud auth fields cannot be empty", "云平台认证字段不能为空", "Cloud auth fields cannot be empty"),
			("Cloud auth missing", "云平台认证信息缺失", "Cloud auth missing"),
			("Cloud connect failed", "云平台连接失败", "Cloud connect failed"),
			("Cloud disconnected", "云平台已断开", "Cloud disconnected"),
			("Cloud connected", "云平台已连接", "Cloud connected"),
			("Skip publish: Cloud not connected", "跳过上报：云平台未连接", "Skip publish: Cloud not connected"),
		]

		for src, zh, en in mapping:
			if text.startswith(src):
				tail = text[len(src) :]
				return f"{zh if self.lang == 'zh' else en}{tail}"
		return text

	def apply_language(self, refresh_status_text=True):
		self.setWindowTitle(self.tr("window_title"))
		self.serial_group.setTitle(self.tr("group_serial"))
		self.aliyun_group.setTitle(self.tr("group_aliyun"))
		self.data_group.setTitle(self.tr("group_data"))
		self.log_group.setTitle(self.tr("group_log"))
		self.access_group.setTitle(self.tr("group_access"))

		self.label_port.setText(self.tr("label_port"))
		self.label_baud.setText(self.tr("label_baud"))
		self.label_serial_status.setText(self.tr("label_status"))
		self.btn_refresh_port.setText(self.tr("btn_refresh"))
		self.btn_open_serial.setText(self.tr("btn_open"))
		self.btn_close_serial.setText(self.tr("btn_close"))

		self.label_product_key.setText(self.tr("label_product_key"))
		self.label_device_name.setText(self.tr("label_device_name"))
		self.label_device_secret.setText(self.tr("label_device_secret"))
		self.label_region.setText(self.tr("label_region"))
		self.label_mqtt_status.setText(self.tr("label_status"))
		self.btn_connect_mqtt.setText(self.tr("btn_connect"))
		self.btn_disconnect_mqtt.setText(self.tr("btn_disconnect"))
		self.show_secret_checkbox.setText(self.tr("show_secret"))
		self.auto_upload_checkbox.setText(self.tr("auto_upload"))

		self.label_last_raw.setText(self.tr("last_raw_json"))
		self.btn_manual_publish.setText(self.tr("btn_manual_publish"))

		self.label_language.setText(self.tr("label_language"))
		self.label_dashboard_urls.setText(self.tr("label_dashboard_urls"))
		self.btn_refresh_urls.setText(self.tr("btn_refresh_urls"))
		self.web_cfg_group.setTitle(self.tr("group_webcfg"))
		self.label_web_backend_mode.setText(self.tr("label_web_backend_mode"))
		self.label_web_product_key.setText(self.tr("label_web_product_key"))
		self.label_web_region.setText(self.tr("label_web_region"))
		self.label_web_consumer_group_id.setText(self.tr("label_web_consumer_group_id"))
		self.label_web_access_key_id.setText(self.tr("label_web_access_key_id"))
		self.label_web_access_key_secret.setText(self.tr("label_web_access_key_secret"))
		self.label_web_amqp_endpoint.setText(self.tr("label_web_amqp_endpoint"))
		self.label_web_amqp_instance_id.setText(self.tr("label_web_amqp_instance_id"))
		self.label_web_device_name.setText(self.tr("label_web_device_name"))
		self.label_web_device_secret.setText(self.tr("label_web_device_secret"))
		self.label_web_mqtt_host.setText(self.tr("label_web_mqtt_host"))
		self.label_web_mqtt_port.setText(self.tr("label_web_mqtt_port"))
		self.label_web_mqtt_tls.setText(self.tr("label_web_mqtt_tls"))
		self.label_web_mqtt_username.setText(self.tr("label_web_mqtt_username"))
		self.label_web_mqtt_password.setText(self.tr("label_web_mqtt_password"))
		self.label_web_mqtt_client_id.setText(self.tr("label_web_mqtt_client_id"))
		self.label_web_host.setText(self.tr("label_web_host"))
		self.label_web_port.setText(self.tr("label_web_port"))
		self.show_web_secret_checkbox.setText(self.tr("show_web_secret"))
		self.btn_load_web_cfg.setText(self.tr("btn_load_web_cfg"))
		self.btn_save_web_cfg.setText(self.tr("btn_save_web_cfg"))
		self.label_dashboard_proc.setText(self.tr("label_dashboard_proc"))
		self.label_dashboard_qr.setText(self.tr("label_dashboard_qr"))
		self.lang_combo.blockSignals(True)
		self.lang_combo.setItemText(0, self.tr("lang_zh"))
		self.lang_combo.setItemText(1, self.tr("lang_en"))
		self.lang_combo.blockSignals(False)
		current_backend = self.web_backend_combo.currentData()
		self.web_backend_combo.blockSignals(True)
		self.web_backend_combo.clear()
		self.web_backend_combo.addItem(self.tr("backend_local_relay"), "local_relay")
		self.web_backend_combo.addItem(self.tr("backend_mqtt_ws"), "mqtt_ws")
		self.web_backend_combo.addItem(self.tr("backend_amqp"), "amqp")
		backend_idx = self.web_backend_combo.findData(current_backend or "local_relay")
		self.web_backend_combo.setCurrentIndex(max(0, backend_idx))
		self.web_backend_combo.blockSignals(False)
		self._set_web_process_status_ui(self.dashboard_access_enabled)

		if refresh_status_text:
			serial_raw = self._last_serial_status_raw or "Serial closed"
			mqtt_raw = self._last_mqtt_status_raw or "Cloud disconnected"
			self.serial_status_label.setText(self.translate_runtime_text(serial_raw))
			self.mqtt_status_label.setText(self.translate_runtime_text(mqtt_raw))

		self.refresh_dashboard_urls(log=False)

	def on_language_changed(self):
		new_lang = self.lang_combo.currentData()
		if new_lang in self.I18N:
			self.lang = new_lang
			self.apply_language(refresh_status_text=True)

	def _resolve_web_host_port(self):
		behavior = self.config.get("behavior", {})
		if hasattr(self, "web_host_edit"):
			host = self.web_host_edit.text().strip() or str(
				behavior.get("web_host_default", "0.0.0.0")
			)
		else:
			host = os.getenv(
				"WEB_HOST", str(behavior.get("web_host_default", "0.0.0.0"))
			).strip()

		if hasattr(self, "web_port_edit"):
			port_text = self.web_port_edit.text().strip() or str(
				behavior.get("web_port_default", 8000)
			)
		else:
			port_text = os.getenv(
				"WEB_PORT", str(behavior.get("web_port_default", 8000))
			).strip()
		try:
			port = int(port_text)
		except Exception:
			port = 8000
		return host, port

	def _build_dashboard_url_map(self):
		host, port = self._resolve_web_host_port()
		local_url = f"http://127.0.0.1:{port}/"
		lan_urls = []
		if host in ("0.0.0.0", "::"):
			ips = detect_lan_ipv4s()
			lan_urls = [f"http://{ip}:{port}/" for ip in ips]
		elif host not in ("127.0.0.1", "localhost", "::1"):
			lan_urls = [f"http://{host}:{port}/"]
		return local_url, lan_urls

	def format_dashboard_urls(self):
		local_url, lan_urls = self._build_dashboard_url_map()
		lines = [f"{self.tr('url_local')}: {local_url}"]
		if lan_urls:
			for url in lan_urls:
				lines.append(f"{self.tr('url_lan')}: {url}")
		else:
			lines.append(self.tr("url_none"))
		if not self.dashboard_access_enabled:
			lines.append(self.tr("url_disabled"))
		return lines, local_url, lan_urls

	def _pick_qr_url(self, local_url, lan_urls):
		if lan_urls:
			return lan_urls[0]
		return local_url

	def _render_qr_for_url(self, url):
		self.dashboard_qr_url_label.setText(url or self.tr("msg_qr_none"))
		if not url:
			self.dashboard_qr_label.setPixmap(QPixmap())
			self.dashboard_qr_label.setText(self.tr("msg_qr_none"))
			return
		if not HAS_QRCODE:
			self.dashboard_qr_label.setPixmap(QPixmap())
			self.dashboard_qr_label.setText(self.tr("msg_qr_dep_missing"))
			return
		try:
			qr = qrcode.QRCode(
				version=1,
				error_correction=qrcode.constants.ERROR_CORRECT_M,
				box_size=8,
				border=2,
			)
			qr.add_data(url)
			qr.make(fit=True)
			img = qr.make_image(fill_color="black", back_color="white")
			buf = BytesIO()
			img.save(buf, format="PNG")
			pm = QPixmap()
			pm.loadFromData(buf.getvalue(), "PNG")
			pm = pm.scaled(
				self.dashboard_qr_label.width() - 10,
				self.dashboard_qr_label.height() - 10,
				Qt.KeepAspectRatio,
				Qt.SmoothTransformation,
			)
			self.dashboard_qr_label.setText("")
			self.dashboard_qr_label.setPixmap(pm)
		except Exception as exc:
			self.dashboard_qr_label.setPixmap(QPixmap())
			self.dashboard_qr_label.setText(self.tr("msg_qr_none"))
			self.log(f"QR render failed: {exc}")

	def _write_dashboard_access_flag(self, enabled):
		try:
			with open(self.dashboard_access_flag_path, "w", encoding="utf-8") as f:
				f.write("1\n" if enabled else "0\n")
			return True
		except Exception as exc:
			self.log(f"Write dashboard access flag failed: {exc}")
			return False

	def _read_dashboard_access_flag(self, default=True):
		if not os.path.exists(self.dashboard_access_flag_path):
			return default
		try:
			with open(self.dashboard_access_flag_path, "r", encoding="utf-8") as f:
				raw = (f.read() or "").strip().lower()
			if raw in ("1", "true", "yes", "on", "enable", "enabled"):
				return True
			if raw in ("0", "false", "no", "off", "disable", "disabled"):
				return False
		except Exception as exc:
			self.log(f"Read dashboard access flag failed: {exc}")
		return default

	def _sync_dashboard_access_from_flag(self, default=True, log=True):
		state = self._read_dashboard_access_flag(default=default)
		if state != self.dashboard_access_enabled:
			self.dashboard_access_enabled = state
			if log:
				self.log(
					self.tr("msg_dashboard_starting")
					if state
					else self.tr("msg_dashboard_stopping")
				)
		self._set_web_process_status_ui(self.dashboard_access_enabled)

	def refresh_dashboard_urls(self, log=True):
		lines, local_url, lan_urls = self.format_dashboard_urls()
		self.dashboard_urls_text.setPlainText("\n".join(lines))
		qr_url = self._pick_qr_url(local_url, lan_urls)
		if not self.dashboard_access_enabled:
			qr_url = ""
		self._render_qr_for_url(qr_url)
		if log:
			for line in lines:
				self.log(f"Dashboard URL => {line}")

	def is_web_process_running(self):
		return self.dashboard_access_enabled

	@staticmethod
	def _decode_output_line(raw):
		for enc in ("utf-8", "gbk"):
			try:
				return raw.decode(enc)
			except UnicodeDecodeError:
				continue
		return raw.decode("utf-8", errors="replace")

	def _stream_web_output(self, proc):
		pipe = getattr(proc, "stdout", None)
		if pipe is None:
			return
		try:
			for line in iter(pipe.readline, b""):
				text = self._decode_output_line(line).rstrip("\r\n")
				if text:
					self.log_signal.emit(f"[WEB] {text}")
		except Exception as exc:
			self.log_signal.emit(f"[WEB] stream error: {exc}")
		finally:
			try:
				pipe.close()
			except Exception:
				pass

	def _set_web_process_status_ui(self, running):
		if running:
			self.dashboard_proc_status_label.setText(self.tr("dashboard_running"))
			self.dashboard_proc_status_label.setStyleSheet("color:#5cb85c;")
			self.btn_toggle_dashboard.setText(self.tr("btn_stop_dashboard"))
		else:
			self.dashboard_proc_status_label.setText(self.tr("dashboard_stopped"))
			self.dashboard_proc_status_label.setStyleSheet("color:#d9534f;")
			self.btn_toggle_dashboard.setText(self.tr("btn_start_dashboard"))

	def _check_web_process_status(self):
		prev = self.dashboard_access_enabled
		self._sync_dashboard_access_from_flag(default=prev, log=False)
		if self.dashboard_access_enabled != prev:
			self.refresh_dashboard_urls(log=True)

	def start_dashboard_process(self):
		self.dashboard_access_enabled = True
		self._write_dashboard_access_flag(True)
		self._set_web_process_status_ui(True)
		self.refresh_dashboard_urls(log=False)
		self.log(self.tr("msg_dashboard_starting"))

	def stop_dashboard_process(self):
		self.dashboard_access_enabled = False
		self._write_dashboard_access_flag(False)
		self._set_web_process_status_ui(False)
		self.refresh_dashboard_urls(log=False)
		self.log(self.tr("msg_dashboard_stopping"))

	def toggle_dashboard_process(self):
		if self.is_web_process_running():
			self.stop_dashboard_process()
		else:
			self.start_dashboard_process()

	def _read_env_map(self):
		data = {}
		if not os.path.exists(self.web_env_path):
			return data
		try:
			with open(self.web_env_path, "r", encoding="utf-8") as f:
				for raw in f:
					line = raw.strip()
					if not line or line.startswith("#") or "=" not in line:
						continue
					k, v = line.split("=", 1)
					data[k.strip()] = v.strip().strip('"').strip("'")
		except Exception as exc:
			self.log(f"Read .env failed: {exc}")
		return data

	def _web_defaults(self):
		cloud = self.config.get("cloud", self.config.get("aliyun", {}))
		behavior = self.config.get("behavior", {})
		return {
			"HUAWEI_BACKEND_MODE": "local_relay",
			"HUAWEI_PRODUCT_KEY": str(cloud.get("product_key", "") or ""),
			"HUAWEI_REGION": str(cloud.get("default_region", "cn-shanghai") or "cn-shanghai"),
			"HUAWEI_CONSUMER_GROUP_ID": "DefaultQueue",
			"HUAWEI_ACCESS_KEY_ID": "",
			"HUAWEI_ACCESS_KEY_SECRET": "",
			"HUAWEI_AMQP_ENDPOINT": "",
			"HUAWEI_AMQP_INSTANCE_ID": "",
			"HUAWEI_DEVICE_NAME": str(cloud.get("device_name", "web_socket") or "web_socket"),
			"HUAWEI_DEVICE_SECRET": str(cloud.get("device_secret", "") or ""),
			"HUAWEI_MQTT_HOST": str(cloud.get("mqtt_host", "") or ""),
			"HUAWEI_MQTT_PORT": str(cloud.get("mqtt_port", 8883) or 8883),
			"HUAWEI_MQTT_TLS": "1" if bool(cloud.get("mqtt_tls", True)) else "0",
			"HUAWEI_MQTT_SIGN_TYPE": "1",
			"HUAWEI_MQTT_USERNAME": str(cloud.get("mqtt_username", "") or ""),
			"HUAWEI_MQTT_PASSWORD": str(cloud.get("mqtt_password", "") or ""),
			"HUAWEI_MQTT_CLIENT_ID": str(cloud.get("mqtt_client_id", "") or ""),
			"WEB_HOST": str(behavior.get("web_host_default", "0.0.0.0") or "0.0.0.0"),
			"WEB_PORT": str(behavior.get("web_port_default", 8000) or 8000),
		}

	def _populate_web_cfg_inputs(self, cfg):
		backend = str(
			cfg.get("HUAWEI_BACKEND_MODE", cfg.get("ALIYUN_BACKEND_MODE", "local_relay"))
			or "local_relay"
		).strip().lower()
		if backend not in ("amqp", "mqtt_ws", "local_relay"):
			if backend in ("mqtt", "wss", "mqtts"):
				backend = "mqtt_ws"
			elif backend in ("local", "relay", "qt_relay"):
				backend = "local_relay"
			else:
				backend = "local_relay"

		idx = self.web_backend_combo.findData(backend)
		if idx < 0:
			idx = self.web_backend_combo.findData("local_relay")
		self.web_backend_combo.setCurrentIndex(max(0, idx))

		self.web_product_key_edit.setText(str(cfg.get("HUAWEI_PRODUCT_KEY", cfg.get("ALIYUN_PRODUCT_KEY", ""))))
		self.web_region_edit.setText(str(cfg.get("HUAWEI_REGION", cfg.get("ALIYUN_REGION", "cn-shanghai"))))
		self.web_consumer_group_edit.setText(str(cfg.get("HUAWEI_CONSUMER_GROUP_ID", cfg.get("ALIYUN_CONSUMER_GROUP_ID", ""))))
		self.web_access_key_id_edit.setText(str(cfg.get("HUAWEI_ACCESS_KEY_ID", cfg.get("ALIYUN_ACCESS_KEY_ID", ""))))
		self.web_access_key_secret_edit.setText(str(cfg.get("HUAWEI_ACCESS_KEY_SECRET", cfg.get("ALIYUN_ACCESS_KEY_SECRET", ""))))
		self.web_amqp_endpoint_edit.setText(str(cfg.get("HUAWEI_AMQP_ENDPOINT", cfg.get("ALIYUN_AMQP_ENDPOINT", ""))))
		self.web_amqp_instance_id_edit.setText(str(cfg.get("HUAWEI_AMQP_INSTANCE_ID", cfg.get("ALIYUN_AMQP_INSTANCE_ID", ""))))
		self.web_device_name_edit.setText(str(cfg.get("HUAWEI_DEVICE_NAME", cfg.get("ALIYUN_DEVICE_NAME", "web_socket"))))
		self.web_device_secret_edit.setText(str(cfg.get("HUAWEI_DEVICE_SECRET", cfg.get("ALIYUN_DEVICE_SECRET", ""))))
		self.web_mqtt_host_edit.setText(str(cfg.get("HUAWEI_MQTT_HOST", cfg.get("ALIYUN_MQTT_HOST", ""))))
		self.web_mqtt_port_edit.setText(str(cfg.get("HUAWEI_MQTT_PORT", cfg.get("ALIYUN_MQTT_PORT", "8883"))))
		mqtt_tls_raw = str(cfg.get("HUAWEI_MQTT_TLS", cfg.get("ALIYUN_MQTT_TLS", "1"))).strip().lower()
		self.web_mqtt_tls_checkbox.setChecked(mqtt_tls_raw in ("1", "true", "yes", "on"))
		self.web_mqtt_username_edit.setText(str(cfg.get("HUAWEI_MQTT_USERNAME", cfg.get("ALIYUN_MQTT_USERNAME", ""))))
		self.web_mqtt_password_edit.setText(str(cfg.get("HUAWEI_MQTT_PASSWORD", cfg.get("ALIYUN_MQTT_PASSWORD", ""))))
		self.web_mqtt_client_id_edit.setText(str(cfg.get("HUAWEI_MQTT_CLIENT_ID", cfg.get("ALIYUN_MQTT_CLIENT_ID", ""))))
		self.web_host_edit.setText(str(cfg.get("WEB_HOST", "0.0.0.0")))
		self.web_port_edit.setText(str(cfg.get("WEB_PORT", "8000")))

	def _collect_web_cfg_inputs(self):
		return {
			"HUAWEI_BACKEND_MODE": str(self.web_backend_combo.currentData() or "local_relay"),
			"HUAWEI_PRODUCT_KEY": self.web_product_key_edit.text().strip(),
			"HUAWEI_REGION": self.web_region_edit.text().strip() or "cn-shanghai",
			"HUAWEI_CONSUMER_GROUP_ID": self.web_consumer_group_edit.text().strip(),
			"HUAWEI_ACCESS_KEY_ID": self.web_access_key_id_edit.text().strip(),
			"HUAWEI_ACCESS_KEY_SECRET": self.web_access_key_secret_edit.text().strip(),
			"HUAWEI_AMQP_ENDPOINT": self.web_amqp_endpoint_edit.text().strip(),
			"HUAWEI_AMQP_INSTANCE_ID": self.web_amqp_instance_id_edit.text().strip(),
			"HUAWEI_DEVICE_NAME": self.web_device_name_edit.text().strip() or "web_socket",
			"HUAWEI_DEVICE_SECRET": self.web_device_secret_edit.text().strip(),
			"HUAWEI_MQTT_HOST": self.web_mqtt_host_edit.text().strip(),
			"HUAWEI_MQTT_PORT": self.web_mqtt_port_edit.text().strip() or "8883",
			"HUAWEI_MQTT_TLS": "1" if self.web_mqtt_tls_checkbox.isChecked() else "0",
			"HUAWEI_MQTT_SIGN_TYPE": "1",
			"HUAWEI_MQTT_USERNAME": self.web_mqtt_username_edit.text().strip(),
			"HUAWEI_MQTT_PASSWORD": self.web_mqtt_password_edit.text().strip(),
			"HUAWEI_MQTT_CLIENT_ID": self.web_mqtt_client_id_edit.text().strip(),
			"WEB_HOST": self.web_host_edit.text().strip() or "0.0.0.0",
			"WEB_PORT": self.web_port_edit.text().strip() or "8000",
		}

	def load_web_config_from_file(self, log=True, notify=True):
		cfg = self._web_defaults()
		cfg.update(self._read_env_map())
		self._populate_web_cfg_inputs(cfg)

		for k, v in self._collect_web_cfg_inputs().items():
			os.environ[k] = str(v)

		self.refresh_dashboard_urls(log=False)
		if log:
			self.log(self.tr("msg_web_cfg_loaded"))
		if notify:
			QMessageBox.information(self, self.tr("info"), self.tr("msg_web_cfg_loaded"))

	def save_web_config_to_file(self):
		try:
			existing = self._read_env_map()
			existing.update(self._collect_web_cfg_inputs())

			order = [
				"HUAWEI_BACKEND_MODE",
				"HUAWEI_PRODUCT_KEY",
				"HUAWEI_REGION",
				"HUAWEI_CONSUMER_GROUP_ID",
				"HUAWEI_ACCESS_KEY_ID",
				"HUAWEI_ACCESS_KEY_SECRET",
				"HUAWEI_AMQP_ENDPOINT",
				"HUAWEI_AMQP_INSTANCE_ID",
				"HUAWEI_DEVICE_NAME",
				"HUAWEI_DEVICE_SECRET",
				"HUAWEI_MQTT_HOST",
				"HUAWEI_MQTT_PORT",
				"HUAWEI_MQTT_TLS",
				"HUAWEI_MQTT_SIGN_TYPE",
				"HUAWEI_MQTT_USERNAME",
				"HUAWEI_MQTT_PASSWORD",
				"HUAWEI_MQTT_CLIENT_ID",
				"WEB_HOST",
				"WEB_PORT",
			]
			remain = [k for k in sorted(existing.keys()) if k not in order]

			with open(self.web_env_path, "w", encoding="utf-8") as f:
				for key in order + remain:
					val = str(existing.get(key, "")).replace("\n", " ").replace("\r", " ").strip()
					f.write(f"{key}={val}\n")

			for k, v in self._collect_web_cfg_inputs().items():
				os.environ[k] = str(v)

			self.refresh_dashboard_urls(log=False)
			self.log(self.tr("msg_web_cfg_saved"))
			QMessageBox.information(self, self.tr("info"), self.tr("msg_web_cfg_saved"))
		except Exception as exc:
			self.log(f"{self.tr('msg_web_cfg_save_failed')}: {exc}")
			QMessageBox.warning(
				self,
				self.tr("warning"),
				f"{self.tr('msg_web_cfg_save_failed')}: {exc}",
			)

	def toggle_web_secret_visibility(self, checked):
		mode = QLineEdit.Normal if checked else QLineEdit.Password
		self.web_access_key_secret_edit.setEchoMode(mode)
		self.web_device_secret_edit.setEchoMode(mode)
		self.web_mqtt_password_edit.setEchoMode(mode)

	def _apply_theme(self):
		self.setStyleSheet(
			"""
			QMainWindow {
				background-color: #f4f7fb;
			}
			QGroupBox {
				border: 1px solid #d9e1ec;
				border-radius: 12px;
				margin-top: 10px;
				padding-top: 12px;
				background-color: #ffffff;
				font-size: 14px;
				font-weight: 600;
				color: #243447;
			}
			QGroupBox::title {
				subcontrol-origin: margin;
				left: 14px;
				padding: 0 6px 0 6px;
			}
			QLabel {
				color: #2f3b4a;
				font-size: 13px;
			}
			QLineEdit, QComboBox, QTextEdit {
				border: 1px solid #d7dee8;
				border-radius: 8px;
				padding: 6px 8px;
				background: #fbfdff;
				selection-background-color: #4a90e2;
				font-size: 13px;
			}
			QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
				border: 1px solid #4a90e2;
				background: #ffffff;
			}
			QPushButton {
				background-color: #2d7ff9;
				color: #ffffff;
				border: none;
				border-radius: 8px;
				padding: 7px 14px;
				font-size: 13px;
				font-weight: 600;
			}
			QPushButton:hover {
				background-color: #1f6fe5;
			}
			QPushButton:pressed {
				background-color: #175ec6;
			}
			QCheckBox {
				font-size: 13px;
				color: #2f3b4a;
			}
			"""
		)

	def _build_ui(self):
		root = QWidget()
		self.setCentralWidget(root)
		main_layout = QVBoxLayout(root)

		top_layout = QGridLayout()
		top_layout.addWidget(self._build_serial_group(), 0, 0)
		top_layout.addWidget(self._build_aliyun_group(), 0, 1)
		top_layout.addWidget(self._build_access_group(), 1, 0, 1, 2)
		main_layout.addLayout(top_layout)

		main_layout.addWidget(self._build_data_group())
		main_layout.addWidget(self._build_log_group())

	def _build_serial_group(self):
		self.serial_group = QGroupBox(self.tr("group_serial"))
		layout = QGridLayout(self.serial_group)

		self.port_combo = QComboBox()
		self.baud_combo = QComboBox()
		self.baud_combo.addItems(self.config["serial"]["baud_rates"])
		self.baud_combo.setCurrentText(self.config["serial"]["default_baud"])

		self.serial_status_label = QLabel(self.tr("disconnected"))
		self.serial_status_label.setStyleSheet("color:#d9534f;")

		self.btn_refresh_port = QPushButton(self.tr("btn_refresh"))
		self.btn_open_serial = QPushButton(self.tr("btn_open"))
		self.btn_close_serial = QPushButton(self.tr("btn_close"))

		self.btn_refresh_port.clicked.connect(self.refresh_ports)
		self.btn_open_serial.clicked.connect(self.open_serial)
		self.btn_close_serial.clicked.connect(self.close_serial)

		self.label_port = QLabel(self.tr("label_port"))
		self.label_baud = QLabel(self.tr("label_baud"))
		self.label_serial_status = QLabel(self.tr("label_status"))

		layout.addWidget(self.label_port, 0, 0)
		layout.addWidget(self.port_combo, 0, 1, 1, 2)
		layout.addWidget(self.label_baud, 1, 0)
		layout.addWidget(self.baud_combo, 1, 1, 1, 2)
		layout.addWidget(self.btn_refresh_port, 2, 0)
		layout.addWidget(self.btn_open_serial, 2, 1)
		layout.addWidget(self.btn_close_serial, 2, 2)
		layout.addWidget(self.label_serial_status, 3, 0)
		layout.addWidget(self.serial_status_label, 3, 1, 1, 2)

		return self.serial_group

	def _build_aliyun_group(self):
		self.aliyun_group = QGroupBox(self.tr("group_aliyun"))
		layout = QGridLayout(self.aliyun_group)
		aliyun_cfg = self.config.get("cloud", self.config.get("aliyun", {}))
		behavior_cfg = self.config["behavior"]

		self.product_key_edit = QLineEdit(aliyun_cfg["product_key"])
		self.device_name_edit = QLineEdit(aliyun_cfg["device_name"])
		self.device_secret_edit = QLineEdit(aliyun_cfg["device_secret"])
		self.device_secret_edit.setEchoMode(QLineEdit.Password)
		self.show_secret_checkbox = QCheckBox(self.tr("show_secret"))
		self.show_secret_checkbox.toggled.connect(self.toggle_secret_visibility)

		self.region_combo = QComboBox()
		self.region_combo.addItems(aliyun_cfg["regions"])
		self.region_combo.setCurrentText(aliyun_cfg["default_region"])

		self.mqtt_status_label = QLabel(self.tr("disconnected"))
		self.mqtt_status_label.setStyleSheet("color:#d9534f;")

		self.btn_connect_mqtt = QPushButton(self.tr("btn_connect"))
		self.btn_disconnect_mqtt = QPushButton(self.tr("btn_disconnect"))
		self.btn_connect_mqtt.clicked.connect(self.connect_mqtt)
		self.btn_disconnect_mqtt.clicked.connect(self.disconnect_mqtt)

		self.auto_upload_checkbox = QCheckBox(self.tr("auto_upload"))
		self.auto_upload_checkbox.setChecked(behavior_cfg["auto_upload"])
		self.show_secret_checkbox.setChecked(behavior_cfg["show_secret"])
		self.toggle_secret_visibility(behavior_cfg["show_secret"])

		self.label_product_key = QLabel(self.tr("label_product_key"))
		self.label_device_name = QLabel(self.tr("label_device_name"))
		self.label_device_secret = QLabel(self.tr("label_device_secret"))
		self.label_region = QLabel(self.tr("label_region"))
		self.label_mqtt_status = QLabel(self.tr("label_status"))

		layout.addWidget(self.label_product_key, 0, 0)
		layout.addWidget(self.product_key_edit, 0, 1, 1, 3)
		layout.addWidget(self.label_device_name, 1, 0)
		layout.addWidget(self.device_name_edit, 1, 1, 1, 3)
		layout.addWidget(self.label_device_secret, 2, 0)
		layout.addWidget(self.device_secret_edit, 2, 1, 1, 2)
		layout.addWidget(self.show_secret_checkbox, 2, 3)
		layout.addWidget(self.label_region, 3, 0)
		layout.addWidget(self.region_combo, 3, 1)
		layout.addWidget(self.btn_connect_mqtt, 3, 2)
		layout.addWidget(self.btn_disconnect_mqtt, 3, 3)
		layout.addWidget(self.auto_upload_checkbox, 4, 0, 1, 3)
		layout.addWidget(self.label_mqtt_status, 5, 0)
		layout.addWidget(self.mqtt_status_label, 5, 1, 1, 3)

		return self.aliyun_group

	def _build_access_group(self):
		self.access_group = QGroupBox(self.tr("group_access"))
		layout = QGridLayout(self.access_group)

		self.label_language = QLabel(self.tr("label_language"))
		self.lang_combo = QComboBox()
		self.lang_combo.addItem(self.tr("lang_zh"), "zh")
		self.lang_combo.addItem(self.tr("lang_en"), "en")
		self.lang_combo.setCurrentIndex(0 if self.lang == "zh" else 1)
		self.lang_combo.currentIndexChanged.connect(self.on_language_changed)

		self.label_dashboard_urls = QLabel(self.tr("label_dashboard_urls"))
		self.dashboard_urls_text = QTextEdit()
		self.dashboard_urls_text.setReadOnly(True)
		self.dashboard_urls_text.setMinimumHeight(82)
		self.dashboard_urls_text.setMaximumHeight(110)
		self.label_dashboard_qr = QLabel(self.tr("label_dashboard_qr"))
		self.dashboard_qr_label = QLabel()
		self.dashboard_qr_label.setAlignment(Qt.AlignCenter)
		self.dashboard_qr_label.setMinimumSize(145, 145)
		self.dashboard_qr_label.setMaximumSize(180, 180)
		self.dashboard_qr_label.setText(self.tr("msg_qr_none"))
		self.dashboard_qr_label.setStyleSheet(
			"border:1px solid #d7dee8;border-radius:8px;background:#ffffff;"
		)
		self.dashboard_qr_url_label = QLabel("")
		self.dashboard_qr_url_label.setWordWrap(True)
		self.dashboard_qr_url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

		self.btn_refresh_urls = QPushButton(self.tr("btn_refresh_urls"))
		self.btn_refresh_urls.clicked.connect(self.refresh_dashboard_urls)
		self.label_dashboard_proc = QLabel(self.tr("label_dashboard_proc"))
		self.dashboard_proc_status_label = QLabel(self.tr("dashboard_stopped"))
		self.dashboard_proc_status_label.setStyleSheet("color:#d9534f;")
		self.btn_toggle_dashboard = QPushButton(self.tr("btn_start_dashboard"))
		self.btn_toggle_dashboard.clicked.connect(self.toggle_dashboard_process)
		self.btn_load_web_cfg = QPushButton(self.tr("btn_load_web_cfg"))
		self.btn_load_web_cfg.clicked.connect(
			lambda: self.load_web_config_from_file(log=True, notify=True)
		)
		self.btn_save_web_cfg = QPushButton(self.tr("btn_save_web_cfg"))
		self.btn_save_web_cfg.clicked.connect(self.save_web_config_to_file)
		qr_box = QWidget()
		qr_layout = QVBoxLayout(qr_box)
		qr_layout.setContentsMargins(0, 0, 0, 0)
		qr_layout.setSpacing(4)
		qr_layout.addWidget(self.label_dashboard_qr)
		qr_layout.addWidget(self.dashboard_qr_label, 0, Qt.AlignLeft)
		qr_layout.addWidget(self.dashboard_qr_url_label)

		layout.addWidget(self.label_language, 0, 0)
		layout.addWidget(self.lang_combo, 0, 1)
		layout.addWidget(self.btn_refresh_urls, 0, 2)
		layout.addWidget(self.label_dashboard_proc, 0, 3)
		layout.addWidget(self.dashboard_proc_status_label, 0, 4)
		layout.addWidget(self.btn_toggle_dashboard, 0, 5)
		layout.addWidget(self.label_dashboard_urls, 1, 0)
		layout.addWidget(self.dashboard_urls_text, 1, 1, 1, 4)
		layout.addWidget(qr_box, 1, 5, 2, 1)
		layout.setColumnStretch(1, 2)
		layout.setColumnStretch(2, 1)
		layout.setColumnStretch(3, 1)
		layout.setColumnStretch(4, 1)

		self.web_cfg_group = QGroupBox(self.tr("group_webcfg"))
		web_layout = QGridLayout(self.web_cfg_group)

		self.label_web_backend_mode = QLabel(self.tr("label_web_backend_mode"))
		self.web_backend_combo = QComboBox()
		self.web_backend_combo.addItem(self.tr("backend_local_relay"), "local_relay")
		self.web_backend_combo.addItem(self.tr("backend_mqtt_ws"), "mqtt_ws")
		self.web_backend_combo.addItem(self.tr("backend_amqp"), "amqp")

		self.label_web_product_key = QLabel(self.tr("label_web_product_key"))
		self.web_product_key_edit = QLineEdit()
		self.label_web_region = QLabel(self.tr("label_web_region"))
		self.web_region_edit = QLineEdit()

		self.label_web_consumer_group_id = QLabel(self.tr("label_web_consumer_group_id"))
		self.web_consumer_group_edit = QLineEdit()
		self.label_web_access_key_id = QLabel(self.tr("label_web_access_key_id"))
		self.web_access_key_id_edit = QLineEdit()
		self.label_web_access_key_secret = QLabel(self.tr("label_web_access_key_secret"))
		self.web_access_key_secret_edit = QLineEdit()
		self.web_access_key_secret_edit.setEchoMode(QLineEdit.Password)
		self.label_web_amqp_endpoint = QLabel(self.tr("label_web_amqp_endpoint"))
		self.web_amqp_endpoint_edit = QLineEdit()
		self.label_web_amqp_instance_id = QLabel(self.tr("label_web_amqp_instance_id"))
		self.web_amqp_instance_id_edit = QLineEdit()

		self.label_web_device_name = QLabel(self.tr("label_web_device_name"))
		self.web_device_name_edit = QLineEdit()
		self.label_web_device_secret = QLabel(self.tr("label_web_device_secret"))
		self.web_device_secret_edit = QLineEdit()
		self.web_device_secret_edit.setEchoMode(QLineEdit.Password)
		self.label_web_mqtt_host = QLabel(self.tr("label_web_mqtt_host"))
		self.web_mqtt_host_edit = QLineEdit()
		self.label_web_mqtt_port = QLabel(self.tr("label_web_mqtt_port"))
		self.web_mqtt_port_edit = QLineEdit()
		self.label_web_mqtt_tls = QLabel(self.tr("label_web_mqtt_tls"))
		self.web_mqtt_tls_checkbox = QCheckBox()
		self.web_mqtt_tls_checkbox.setChecked(True)
		self.label_web_mqtt_username = QLabel(self.tr("label_web_mqtt_username"))
		self.web_mqtt_username_edit = QLineEdit()
		self.label_web_mqtt_password = QLabel(self.tr("label_web_mqtt_password"))
		self.web_mqtt_password_edit = QLineEdit()
		self.web_mqtt_password_edit.setEchoMode(QLineEdit.Password)
		self.label_web_mqtt_client_id = QLabel(self.tr("label_web_mqtt_client_id"))
		self.web_mqtt_client_id_edit = QLineEdit()

		self.label_web_host = QLabel(self.tr("label_web_host"))
		self.web_host_edit = QLineEdit()
		self.label_web_port = QLabel(self.tr("label_web_port"))
		self.web_port_edit = QLineEdit()

		self.show_web_secret_checkbox = QCheckBox(self.tr("show_web_secret"))
		self.show_web_secret_checkbox.toggled.connect(self.toggle_web_secret_visibility)

		web_layout.addWidget(self.label_web_backend_mode, 0, 0)
		web_layout.addWidget(self.web_backend_combo, 0, 1)
		web_layout.addWidget(self.btn_load_web_cfg, 0, 2)
		web_layout.addWidget(self.btn_save_web_cfg, 0, 3)
		web_layout.addWidget(self.show_web_secret_checkbox, 0, 4)

		web_layout.addWidget(self.label_web_product_key, 1, 0)
		web_layout.addWidget(self.web_product_key_edit, 1, 1)
		web_layout.addWidget(self.label_web_region, 1, 2)
		web_layout.addWidget(self.web_region_edit, 1, 3)

		web_layout.addWidget(self.label_web_consumer_group_id, 2, 0)
		web_layout.addWidget(self.web_consumer_group_edit, 2, 1)
		web_layout.addWidget(self.label_web_access_key_id, 2, 2)
		web_layout.addWidget(self.web_access_key_id_edit, 2, 3)

		web_layout.addWidget(self.label_web_access_key_secret, 3, 0)
		web_layout.addWidget(self.web_access_key_secret_edit, 3, 1)
		web_layout.addWidget(self.label_web_amqp_endpoint, 3, 2)
		web_layout.addWidget(self.web_amqp_endpoint_edit, 3, 3, 1, 3)

		web_layout.addWidget(self.label_web_device_secret, 4, 0)
		web_layout.addWidget(self.web_device_secret_edit, 4, 1)
		web_layout.addWidget(self.label_web_amqp_instance_id, 4, 2)
		web_layout.addWidget(self.web_amqp_instance_id_edit, 4, 3)
		web_layout.addWidget(self.label_web_device_name, 4, 4)
		web_layout.addWidget(self.web_device_name_edit, 4, 5)

		web_layout.addWidget(self.label_web_mqtt_host, 5, 0)
		web_layout.addWidget(self.web_mqtt_host_edit, 5, 1, 1, 3)
		web_layout.addWidget(self.label_web_mqtt_port, 5, 4)
		web_layout.addWidget(self.web_mqtt_port_edit, 5, 5)

		web_layout.addWidget(self.label_web_mqtt_tls, 6, 0)
		web_layout.addWidget(self.web_mqtt_tls_checkbox, 6, 1)
		web_layout.addWidget(self.label_web_mqtt_username, 6, 2)
		web_layout.addWidget(self.web_mqtt_username_edit, 6, 3)
		web_layout.addWidget(self.label_web_mqtt_password, 6, 4)
		web_layout.addWidget(self.web_mqtt_password_edit, 6, 5)

		web_layout.addWidget(self.label_web_mqtt_client_id, 7, 0)
		web_layout.addWidget(self.web_mqtt_client_id_edit, 7, 1, 1, 3)
		web_layout.addWidget(self.label_web_host, 7, 4)
		web_layout.addWidget(self.web_host_edit, 7, 5)
		web_layout.addWidget(self.label_web_port, 8, 4)
		web_layout.addWidget(self.web_port_edit, 8, 5)

		layout.addWidget(self.web_cfg_group, 3, 0, 1, 6)
		return self.access_group

	def _build_data_group(self):
		self.data_group = QGroupBox(self.tr("group_data"))
		layout = QHBoxLayout(self.data_group)

		form = QFormLayout()
		self.soil_label = QLabel("-")
		self.hum_label = QLabel("-")
		self.temp_label = QLabel("-")
		self.co2_label = QLabel("-")
		self.light_label = QLabel("-")

		form.addRow("SoilMoisture", self.soil_label)
		form.addRow("CurrentHumidity", self.hum_label)
		form.addRow("CurrentTemperature", self.temp_label)
		form.addRow("co2", self.co2_label)
		form.addRow("LightLux", self.light_label)

		self.raw_text = QTextEdit()
		self.raw_text.setReadOnly(True)

		right_layout = QVBoxLayout()
		self.label_last_raw = QLabel(self.tr("last_raw_json"))
		right_layout.addWidget(self.label_last_raw)
		right_layout.addWidget(self.raw_text)

		self.btn_manual_publish = QPushButton(self.tr("btn_manual_publish"))
		self.btn_manual_publish.clicked.connect(self.manual_publish)
		right_layout.addWidget(self.btn_manual_publish)

		layout.addLayout(form, 1)
		layout.addLayout(right_layout, 2)
		return self.data_group

	def _build_log_group(self):
		self.log_group = QGroupBox(self.tr("group_log"))
		layout = QVBoxLayout(self.log_group)
		self.log_text = QTextEdit()
		self.log_text.setReadOnly(True)
		layout.addWidget(self.log_text)
		return self.log_group

	def refresh_ports(self):
		self.port_combo.clear()
		merged = {}

		# Primary channel: pyserial
		for item in serial.tools.list_ports.comports():
			device = str(getattr(item, "device", "") or "").strip().upper()
			if not device:
				continue
			merged[device] = {
				"device": device,
				"description": str(getattr(item, "description", "") or "Unknown"),
				"manufacturer": str(getattr(item, "manufacturer", "") or ""),
				"product": str(getattr(item, "product", "") or ""),
				"interface": str(getattr(item, "interface", "") or ""),
				"hwid": str(getattr(item, "hwid", "") or ""),
				"source": "pyserial",
			}

		# Fallback channel: Windows PnP (helps when pyserial misses virtual ports)
		for item in self._scan_windows_pnp_ports():
			device = item["device"].upper()
			if device in merged:
				merged[device]["source"] = "pyserial+pnp"
				if merged[device].get("description", "") in ("", "Unknown"):
					merged[device]["description"] = item.get("description", "Unknown")
				if not merged[device].get("manufacturer"):
					merged[device]["manufacturer"] = item.get("manufacturer", "")
				if not merged[device].get("hwid"):
					merged[device]["hwid"] = item.get("device_id", "")
			else:
				merged[device] = {
					"device": device,
					"description": item.get("description", "Unknown"),
					"manufacturer": item.get("manufacturer", ""),
					"product": "",
					"interface": item.get("pnp_class", ""),
					"hwid": item.get("device_id", ""),
					"source": "pnp",
				}

		if not merged:
			self.log("No serial ports found")
			return

		entries = []
		for data in merged.values():
			score, reason = self._virtual_match_score(data)
			entries.append((data, score, reason))

		entries.sort(
			key=lambda x: (
				0 if x[1] > 0 else 1,
				-x[1],
				x[0]["device"],
			)
		)

		first_virtual_index = -1
		for index, (item, score, reason) in enumerate(entries):
			desc = item.get("description") or "Unknown"
			virtual_tag = " [Virtual]" if score > 0 else ""
			source_tag = f" [{item.get('source', 'unknown')}]"
			display = f"{item['device']} | {desc}{virtual_tag}{source_tag}"
			self.port_combo.addItem(display, item["device"])
			if first_virtual_index < 0 and score > 0:
				first_virtual_index = index

			self.log(
				"Port detect: "
				f"{item['device']}, desc={desc}, source={item.get('source')}, "
				f"virtual_score={score}, reason={reason if reason else 'none'}"
			)

		if first_virtual_index >= 0:
			self.port_combo.setCurrentIndex(first_virtual_index)
			self.log("Auto-selected first virtual serial port")

		selected_text = self.port_combo.currentText()
		self.log(f"Ports refreshed, selected: {selected_text}")

	def _scan_windows_pnp_ports(self):
		if not sys.platform.startswith("win"):
			return []

		ps_script = (
			"$items = Get-CimInstance Win32_PnPEntity "
			"| Where-Object { $_.Name -match 'COM\\d+' } "
			"| Select-Object Name,Description,Manufacturer,PNPClass,DeviceID; "
			"$items | ConvertTo-Json -Compress"
		)

		try:
			proc = subprocess.run(
				["powershell", "-NoProfile", "-Command", ps_script],
				capture_output=True,
				text=True,
				timeout=self.config["behavior"]["pnp_scan_timeout_sec"],
				encoding="utf-8",
				errors="ignore",
			)
		except Exception as exc:
			self.log(f"PnP scan failed to start: {exc}")
			return []

		if proc.returncode != 0:
			stderr_text = (proc.stderr or "").strip()
			if stderr_text:
				self.log(f"PnP scan error: {stderr_text}")
			return []

		stdout_text = (proc.stdout or "").strip()
		if not stdout_text:
			return []

		try:
			items = json.loads(stdout_text)
		except Exception:
			self.log("PnP scan output parse failed")
			return []

		if isinstance(items, dict):
			items = [items]
		if not isinstance(items, list):
			return []

		ports = []
		for item in items:
			if not isinstance(item, dict):
				continue

			name = str(item.get("Name") or "")
			matches = re.findall(r"(COM\d+)", name, flags=re.IGNORECASE)
			if not matches:
				continue

			for port in matches:
				ports.append(
					{
						"device": port.upper(),
						"description": name or str(item.get("Description") or "Unknown"),
						"manufacturer": str(item.get("Manufacturer") or ""),
						"pnp_class": str(item.get("PNPClass") or ""),
						"device_id": str(item.get("DeviceID") or ""),
					}
				)

		self.log(f"PnP scan found {len(ports)} COM entries")
		return ports

	@staticmethod
	def _virtual_match_score(port_item):
		def _get(field):
			if isinstance(port_item, dict):
				return str(port_item.get(field, "") or "")
			return str(getattr(port_item, field, "") or "")

		text = " ".join(
			[
				_get("device"),
				_get("name"),
				_get("description"),
				_get("manufacturer"),
				_get("product"),
				_get("interface"),
				_get("hwid"),
				_get("source"),
			]
		).lower()

		score = 0
		reasons = []

		keyword_weights = {
			"virtual serial": 4,
			"virtual": 3,
			"eltima": 5,
			"com0com": 5,
			"vsp": 2,
			"vspd": 5,
			"hub4com": 5,
			"tty0tty": 5,
			"����": 4,
		}

		for keyword, weight in keyword_weights.items():
			if keyword in text:
				score += weight
				reasons.append(keyword)

		if re.search(r"com\d+\s*<[-=]+>\s*com\d+", text):
			score += 6
			reasons.append("com-pair-arrow")

		if re.search(r"com\d+\s*to\s*com\d+", text):
			score += 5
			reasons.append("com-pair-to")

		return score, ",".join(reasons)

	def open_serial(self):
		port = (self.port_combo.currentData() or "").strip()
		if not port:
			current = self.port_combo.currentText().strip()
			port = current.split("|")[0].strip() if current else ""
		if not port:
			QMessageBox.warning(self, self.tr("warning"), self.tr("msg_no_port"))
			return
		baud = int(self.baud_combo.currentText())
		self.serial_thread.open_port(port, baud)

	def toggle_secret_visibility(self, checked):
		self.device_secret_edit.setEchoMode(
			QLineEdit.Normal if checked else QLineEdit.Password
		)

	def close_serial(self):
		self.serial_thread.close_port()

	def connect_mqtt(self):
		cloud_cfg = self.config.get("cloud", self.config.get("aliyun", {}))
		env_cfg = self._read_env_map()
		def _env_pick(*keys):
			for key in keys:
				val = str(env_cfg.get(key, "") or "").strip()
				if val:
					return val
			return ""
		def _to_int(raw, default):
			try:
				return int(str(raw).strip())
			except Exception:
				return int(default)
		def _to_bool(raw, default=False):
			if raw is None:
				return bool(default)
			return str(raw).strip().lower() in ("1", "true", "yes", "on")

		mqtt_host = _env_pick("HUAWEI_MQTT_HOST", "ALIYUN_MQTT_HOST") or str(
			cloud_cfg.get("mqtt_host", "") or ""
		)
		mqtt_port = _to_int(
			_env_pick("HUAWEI_MQTT_PORT", "ALIYUN_MQTT_PORT")
			or cloud_cfg.get("mqtt_port", 1883),
			1883,
		)
		mqtt_tls = _to_bool(
			_env_pick("HUAWEI_MQTT_TLS", "ALIYUN_MQTT_TLS")
			or cloud_cfg.get("mqtt_tls", False),
			False,
		)
		mqtt_username = _env_pick("HUAWEI_MQTT_USERNAME", "ALIYUN_MQTT_USERNAME") or str(
			cloud_cfg.get("mqtt_username", "") or ""
		)
		mqtt_password = _env_pick("HUAWEI_MQTT_PASSWORD", "ALIYUN_MQTT_PASSWORD") or str(
			cloud_cfg.get("mqtt_password", "") or ""
		)
		mqtt_client_id = _env_pick("HUAWEI_MQTT_CLIENT_ID", "ALIYUN_MQTT_CLIENT_ID") or str(
			cloud_cfg.get("mqtt_client_id", "") or ""
		)
		service_id = _env_pick("HUAWEI_SERVICE_ID", "ALIYUN_SERVICE_ID") or str(
			cloud_cfg.get("service_id", "env_monitor") or "env_monitor"
		)
		region = _env_pick("HUAWEI_REGION", "ALIYUN_REGION") or self.region_combo.currentText()
		product_key = _env_pick("HUAWEI_PRODUCT_KEY", "ALIYUN_PRODUCT_KEY") or self.product_key_edit.text()
		platform = _env_pick("CLOUD_PLATFORM") or str(
			cloud_cfg.get("platform", "huawei") or "huawei"
		)

		self.aliyun.connect(
			product_key,
			self.device_name_edit.text(),
			self.device_secret_edit.text(),
			region,
			platform=platform,
			mqtt_host=mqtt_host,
			mqtt_port=mqtt_port,
			mqtt_tls=mqtt_tls,
			mqtt_username=mqtt_username,
			mqtt_password=mqtt_password,
			mqtt_client_id=mqtt_client_id,
			service_id=service_id,
		)

	def disconnect_mqtt(self):
		self.aliyun.disconnect()

	def on_serial_status(self, ok, text):
		self._last_serial_status_raw = text
		self.serial_status_label.setText(self.translate_runtime_text(text))
		self.serial_status_label.setStyleSheet(
			"color:#5cb85c;" if ok else "color:#d9534f;"
		)
		self.log(self.translate_runtime_text(text))

	def on_mqtt_status(self, ok, text):
		self._last_mqtt_status_raw = text
		self.mqtt_status_label.setText(self.translate_runtime_text(text))
		self.mqtt_status_label.setStyleSheet(
			"color:#5cb85c;" if ok else "color:#d9534f;"
		)
		self.log(self.translate_runtime_text(text))

	def on_mqtt_message(self, topic, payload):
		self.log(f"MQTT <= {topic}: {payload}")

	def on_serial_line(self, line):
		self.raw_text.setPlainText(line)
		self.log(f"Serial <= {line}")
		objs = self._decode_serial_payloads(line)
		if not objs:
			self.log("JSON parse failed: no valid object decoded from serial line")
			return

		for obj in objs:
			params = self.normalize_params(obj)
			if not params:
				continue
			self.latest_params = params
			self.update_data_labels(params)
			self.emit_local_relay(params)
			if self.auto_upload_checkbox.isChecked():
				self.aliyun.publish_properties(params)

	def _decode_serial_payloads(self, line):
		text = str(line or "").strip()
		if not text:
			return []

		# Fast path: single JSON object/array.
		try:
			data = json.loads(text)
			if isinstance(data, dict):
				return [data]
			if isinstance(data, list):
				return [x for x in data if isinstance(x, dict)]
		except Exception:
			pass

		# Tolerate concatenated JSON objects in one serial frame.
		decoder = json.JSONDecoder()
		out = []
		idx = 0
		n = len(text)
		while idx < n:
			while idx < n and text[idx] in " \t\r\n,;":
				idx += 1
			if idx >= n:
				break
			try:
				obj, end = decoder.raw_decode(text, idx)
			except Exception:
				break
			idx = end
			if isinstance(obj, dict):
				out.append(obj)
			elif isinstance(obj, list):
				out.extend([x for x in obj if isinstance(x, dict)])
		return out

	def emit_local_relay(self, params):
		if not params:
			return

		behavior = self.config.get("behavior", {})
		if not behavior.get("local_relay_enable", True):
			return

		host = behavior.get("local_relay_host", "127.0.0.1")
		port = int(behavior.get("local_relay_port", 19091))
		payload = {
			"source": "qt_local",
			"params": params,
			"time": int(time.time()),
		}

		try:
			data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
			sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			try:
				sock.sendto(data, (host, port))
			finally:
				sock.close()
			self._relay_error_logged = False
		except Exception as exc:
			if not self._relay_error_logged:
				self.log(f"Local relay send failed: {exc}")
				self._relay_error_logged = True

	def normalize_params(self, obj):
		# Compatible with both old payload and new flattened payload.
		params = {}
		if not isinstance(obj, dict):
			return params

		lower_map = {str(k).strip().lower(): v for k, v in obj.items()}
		def _pick(*aliases):
			for a in aliases:
				if a in obj:
					return obj.get(a)
				lk = str(a).strip().lower()
				if lk in lower_map:
					return lower_map.get(lk)
			return None

		soil_v = _pick("SoilMoisture", "soil", "soil_moisture", "soilhumidity")
		if soil_v is not None:
			params["SoilMoisture"] = self.to_int(soil_v)

		hum_v = _pick("CurrentHumidity", "current_humidity", "humidity", "hum")
		if hum_v is not None:
			params["CurrentHumidity"] = self.to_int(hum_v)
		elif isinstance(obj.get("air1"), dict):
			params["CurrentHumidity"] = self.to_int(obj.get("air1", {}).get("h"))

		temp_v = _pick("CurrentTemperature", "current_temperature", "temperature", "temp")
		if temp_v is not None:
			params["CurrentTemperature"] = self.to_int(temp_v)
		elif isinstance(obj.get("air1"), dict):
			params["CurrentTemperature"] = self.to_int(obj.get("air1", {}).get("t"))

		co2_v = _pick("co2", "CO2", "co_2")
		if co2_v is not None:
			params["co2"] = self.to_int(co2_v)

		light_v = _pick("LightLux", "light", "light_lux", "lux")
		if light_v is not None:
			params["LightLux"] = self.to_int(light_v)

		# Remove invalid values so that cloud side validation is cleaner.
		params = {k: v for k, v in params.items() if v is not None}
		return params

	@staticmethod
	def to_int(value):
		try:
			if value is None:
				return None
			if isinstance(value, str):
				s = value.strip()
				if not s:
					return None
				m = re.search(r"-?\d+(?:\.\d+)?", s)
				if not m:
					return None
				return int(float(m.group(0)))
			return int(float(value))
		except Exception:
			return None

	def update_data_labels(self, params):
		self.soil_label.setText(str(params.get("SoilMoisture", "-")))
		self.hum_label.setText(str(params.get("CurrentHumidity", "-")))
		self.temp_label.setText(str(params.get("CurrentTemperature", "-")))
		self.co2_label.setText(str(params.get("co2", "-")))
		self.light_label.setText(str(params.get("LightLux", "-")))

	def manual_publish(self):
		if not self.latest_params:
			QMessageBox.information(self, self.tr("info"), self.tr("msg_no_data"))
			return
		self.aliyun.publish_properties(self.latest_params)

	def log(self, text):
		self.log_signal.emit(str(text))

	def _append_log(self, text):
		ts = time.strftime("%H:%M:%S")
		self.log_text.append(f"[{ts}] {text}")

	def closeEvent(self, event):
		if hasattr(self, "dashboard_access_watchdog"):
			self.dashboard_access_watchdog.stop()
		self.serial_thread.close_port()
		self.aliyun.disconnect()
		super().closeEvent(event)


def main():
	app = QApplication(sys.argv)
	win = MainWindow()
	win.show()
	sys.exit(app.exec_())


if __name__ == "__main__":
	main()

