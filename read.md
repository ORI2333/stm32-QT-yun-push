## 前言
此项目为接单项目，负责数据上云和下发数据部分

## 需求
温室的功能需求包括加热、制冷、加湿、光照等部分,作为温室的核心,需要保证设备达到课题的需求,能实现温度、湿度、光照等的调节,以及达到对当地气候进行模拟。
a.选择合适的环境传感器，能够检测环境温湿度、光照强度、土壤湿度、二氧化碳浓度等；
b.温度调节采用PTC加热器升温与半导体制冷器降温；
c.湿度调节采用超声波雾化加湿器加湿；
d.光强调节采用LED补光灯和遮阳帘调节；
e.CO2浓度采用负压风机调节；
f.水肥采用水肥一体化系统进行调节，水肥一体化系统包括水泵、电磁阀、水箱、营养箱和混合箱,水泵进行水肥的抽取,电磁阀控制水肥抽取的时间,通过改变水肥的输送比例进行灌溉作业；

g.可通过连接WIFI进行远程监控,实现手机端实时查看微型温室内各个环境的数据,对环境信息的远距离监

提醒功能，当测的环境参数超过设定阈值就提醒

## 工具链
**软件：**
- proteus8.15.SP1：[参考这个文章就行](https://blog.csdn.net/xiaoningaijishu/article/details/147325475)
- keil5
- vscode
- Configure Virtual Serial Port Driver（虚拟串口软件）

- 安卓webview

**环境依赖：**
- Python3.12及其以上
- PyQt5 5.15.11
- pyserial 3.5
- paho-mqtt 1.6.1
- qrcode 7.4.2
- fastapi 0.115.12
- uvicorn 0.34.2
## 仿真器件列表
如下图
ps：proteus此仿真并非笔者所设计，进攻参考
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260429001152511.png?imageSlim)

## 检测数据
STM32中的数据都是无符号16位
示例：
```json
{"light":36,"co2":54,"air1":{"t":30,"h":35},"air2":{"t":27,"h":41},"soil":41}
```
- linght：光照强度（ADC in2）
- co2：二氧化碳浓度（ADC in4）
- air1_h：湿度（DHT11_1）
- air1_t：温度(DHT11_1)
- air2_h:土壤湿度(DHT11_2)
- air2_t:土壤温度(DHT11_2)
- soil：土壤湿度(DHT11_2)

## 云平台
[阿里云物联网云平台](https://iot.console.aliyun.com/lk/vpc/instance/detail_s)
更新为华为云，阿里云新用户不支持使用公共免费实例，切换华为云
[华为云物联网控制台](https://console.huaweicloud.com/iotdm/?region=cn-east-3&locale=zh-cn#/dm-dev/all-product)
### 创建产品
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260425164401369.png?imageSlim)
使用MQTT协议、JSON格式

### 创建模型
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260425164502436.png?imageSlim)
服务：
- `env_monitor`（环境监测）
属性与单位建议：
1. `soil_moisture`
	- 中文：土壤湿度
	- 单位：`%`（体积含水率或相对湿度百分比）
	- 数据类型建议：`int，看传感器精度）
	- 典型范围：`0 ~ 100`
2. `current_humidity`
	- 中文：当前空气湿度
	- 单位：`%RH`
	- 数据类型建议：int
	- 典型范围：`0 ~ 100`
3. `current_temperature`
	- 中文：当前温度
	- 单位：`℃`
	- 数据类型建议：`int`
	- 典型范围：`-40 ~ 125`（按你传感器能力可缩小）
4. `co2`
	- 中文：二氧化碳浓度
	- 单位：`ppm`
	- 数据类型建议：
	- 典型范围：`0 ~ 10000`（室内常用 400~5000）
5. `light_lux`
	- 中文：光照度
	- 单位：`lx`
	- 数据类型建议：`int`
	- 典型范围：`0 ~ 100000`
6. 中文显示名分别配成土壤湿度、当前湿度、当前温度、二氧化碳、光照值
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260425165046365.png?imageSlim)
### 注册设备
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260425165152324.png?imageSlim)
### 保存密钥
设备id：69ec7ee918855b39c5128106_QT_test1
设备密钥：266e1cde ~隐藏~ 5c0212b9a18f
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260425165249794.png?imageSlim)

### 接入信息
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260425175630846.png?imageSlim)
获得：
{
    "access_key": "DSYC9gpR",
    "access_code": "9KGfv8oPIU~隐藏~uudzqAKcUGs6",
    "type": "AMQP"
}

## 更换华为云账号 / 新建产品和设备后需修改的配置说明
# 更换华为云账号 / 新建产品和设备后需修改的配置说明

本文档说明在华为云 IoTDA 控制台新建（或切换）产品与设备后，项目中需要同步修改的配置文件和代码位置。

---

### 一、`host/.env` — Web 看板与云端连接的核心配置文件
**文件路径：** [host/.env](host/.env)
这是最核心的配置文件，被 [qt.py](qt.py) 和 [web_dashboard.py](web_dashboard.py) 共同读取。更换账号后，以下字段需要填写新值：
#### 1. 设备 MQTT 连接配置（必填）

|配置项|说明|在华为云控制台的位置|
|---|---|---|
|`HUAWEI_DEVICE_NAME`|设备名称|IoTDA 控制台 → 设备 → 设备详情|
|`HUAWEI_DEVICE_SECRET`|设备密钥|注册设备时生成的密钥|
|`HUAWEI_MQTT_HOST`|MQTT 接入地址|IoTDA 控制台 → 总览 → 接入信息 → MQTT 设备接入地址|
|`HUAWEI_MQTT_PORT`|MQTT 端口|固定 `8883`（TLS）|
|`HUAWEI_MQTT_TLS`|是否启用 TLS|固定 `1`|
|`HUAWEI_REGION`|区域|如 `cn-east-3`、`cn-shanghai` 等|

#### 2. AMQP 模式配置（仅当 `HUAWEI_BACKEND_MODE=amqp` 时需要）

|配置项|说明|在华为云控制台的位置|
|---|---|---|
|`HUAWEI_ACCESS_KEY_ID`|访问密钥 ID|华为云控制台 → 我的凭证 → 访问密钥|
|`HUAWEI_ACCESS_KEY_SECRET`|访问密钥 Secret|同上|
|`HUAWEI_AMQP_ENDPOINT`|AMQP 接入端点|IoTDA 控制台 → 规则 → 数据转发 → AMQP 队列|
|`HUAWEI_AMQP_INSTANCE_ID`|实例 ID（新版必填）|同上|
|`HUAWEI_CONSUMER_GROUP_ID`|队列名称|默认 `DefaultQueue`|

#### 3. 其他配置

|配置项|说明|
|---|---|
|`HUAWEI_BACKEND_MODE`|后端模式：`local_relay`（推荐）/ `mqtt_ws` / `amqp`|
|`HUAWEI_PRODUCT_KEY`|产品 ProductKey（非华为云 MQTT 必填，华为云可留空）|
|`LOCAL_RELAY_ENABLE`|本地 UDP 转发开关，固定 `1`|
|`WEB_HOST` / `WEB_PORT`|Web 看板监听地址和端口|

---

### 二、`host/qt.py` — Qt 桌面程序的默认值

**文件路径：** [host/qt.py:48-84](host/qt.py#L48-L84)
在 `APP_CONFIG["cloud"]` 字典中有硬编码的默认值。更换账号后建议修改以下行：
#### 需要修改的字段（第 59-73 行）

"cloud": {  
    "product_key": "a17MwdB5xAq",                                          # 改为新产品的 ProductKey  
    "device_name": "your_device_id",                                       # 改为新设备名称  
    "device_secret": "your_device_secret",                                 # 改为新设备密钥  
    "platform": "huawei",  
    "mqtt_host": "your-instance.st1.iotda-device.cn-east-3.myhuaweicloud.com",  # 改为新实例的 MQTT 接入地址  
    "mqtt_port": 8883,  
    "mqtt_tls": True,  
    "mqtt_username": "",                                                   # 华为云留空即可（自动签名）  
    "mqtt_password": "",  
    "mqtt_client_id": "",  
    "service_id": "env_monitor",  
    "regions": ["cn-east-3", "cn-shanghai", "cn-beijing", "cn-shenzhen", "cn-hangzhou"],  
    "default_region": "cn-east-3",                                        # 改为实例所在区域  
},

#### 关键字段说明

|字段|是否必改|说明|
|---|---|---|
|`product_key`|**是**|华为云 IoTDA 控制台 → 产品 → ProductKey|
|`device_name`|**是**|注册设备时的设备名称|
|`device_secret`|**是**|设备注册时生成的密钥|
|`mqtt_host`|**是**|IoTDA 控制台 → 总览 → MQTT 设备接入地址（格式：`xxx.st1.iotda-device.cn-east-3.myhuaweicloud.com`）|
|`default_region`|**是**|按实例所在区域填写|
|`service_id`|否|与产品中定义的服务 ID 一致，默认 `env_monitor`|

> **提示：** 也可以在 Qt 程序运行后通过 UI 界面直接填入 `ProductKey`、`DeviceName`、`DeviceSecret`、`Region` 等字段，无需每次修改代码。上述修改只是更改程序**启动时的默认值**。UI 中填写的值还可以通过点击 **"保存 .env"** 按钮持久化到 `.env` 文件。

---

### 三、`host/web_dashboard.py` — Web 看板程序

**文件路径：** [host/web_dashboard.py:136-150](host/web_dashboard.py#L136-L150)

该文件**完全从 `.env` 文件读取配置**，不存在必须修改的硬编码值。唯一需要注意的是 `load_huawei_config()` 函数中有一行硬编码的默认 ProductKey（仅作为 fallback）：

 第 138 行  
product_key=_env_cloud("HUAWEI_PRODUCT_KEY", "ALIYUN_PRODUCT_KEY", "a17MwdB5xAq"),

建议将最后一个默认值 `"a17MwdB5xAq"` 改为空字符串 `""` 或新产品 Key，避免旧值残留。

#### web_dashboard.py 支持的三种后端模式

|模式|配置值|说明|
|---|---|---|
|**本地转发（推荐）**|`local_relay`|仅监听 qt.py 通过 UDP 127.0.0.1:19091 转发的数据，无需额外云配置|
|**MQTT(S)**|`mqtt_ws`|Web 直接连接华为云 MQTT，需填写 HUAWEI_DEVICE_NAME/SECRET 和 HUAWEI_MQTT_HOST|
|**AMQP**|`amqp`|云平台拉取模式，需填写 AMQP 全套配置 + 安装 `python-qpid-proton`|

---

### 四、`host/run_all.py` — 启动器

**文件路径：** [host/run_all.py](host/run_all.py)

此文件是纯启动器（同时启动 qt.py 和 web_dashboard.py），**不包含任何云端配置信息**，更换账号无需修改。

---

### 五、新账号更换操作步骤汇总

按以下顺序操作：
#### 步骤 1：在华为云 IoTDA 控制台操作
1. 登录 **华为云控制台** → **IoTDA 设备接入**
2. 创建 **产品**（获取 ProductKey）
3. 在产品下 **注册设备**（获取 DeviceName、DeviceSecret）
4. 记下 **MQTT 接入地址**（控制台总览页 → 接入信息）
5. 如需 AMQP 模式，创建 **访问密钥**（我的凭证 → 访问密钥）和 **AMQP 队列**
#### 步骤 2：修改 `host/.env`

HUAWEI_BACKEND_MODE=local_relay    # 或 amqp / mqtt_ws  
HUAWEI_DEVICE_NAME=新设备名称  
HUAWEI_DEVICE_SECRET=新设备密钥  
HUAWEI_MQTT_HOST=新实例的MQTT接入地址  
HUAWEI_MQTT_PORT=8883  
HUAWEI_MQTT_TLS=1  
HUAWEI_REGION=实例所在区域  

 如果用 AMQP 模式，还需要填 AMQP 相关字段

#### 步骤 3：修改 `host/qt.py` 默认值（可选）

修改 [qt.py:59-73](qt.py#L59-L73) 的 `APP_CONFIG["cloud"]` 字典中的默认值。如果每次都在 UI 中手动填写并保存 `.env`，则可跳过此步。
#### 步骤 4：启动并验证
1. 双击 `run_all.py` 或执行 `python host/run_all.py`
2. 在 Qt 窗口中点击 **"连接"** 按钮，确认状态变为 **"云平台已连接"**
3. 浏览器打开 `http://127.0.0.1:8000/` 确认 Web 看板正常显示数据
---
### 注意事项

1. **DeviceName 互斥：** qt.py 和 web_dashboard.py（MQTT/AMQP 模式）如果使用**同一个** DeviceName + DeviceSecret 连接华为云，云平台可能会强制断开其中一个连接。建议：
    - 推荐使用 `local_relay` 模式（Web 从 qt.py 本地转发获取数据，不直接连云平台）
    - 如果必须两处同时连接，注册两个不同的设备
2. **密钥安全：** `.env` 文件包含敏感信息，已被 `.gitignore` 排除，**切勿提交到 Git**
3. **区域一致性：** IoTDA 实例的区域必须与 `.env` 中的 `HUAWEI_REGION` 以及 qt.py 中选择的区域一致
## 使用教程
打开proteus
下载.hex文件
设置端口号和波特率
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260429152653004.png?imageSlim)

打开Configure Virtual Serial Port Driver
设置虚拟端口，如图设置com10和11
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260429152739435.png?imageSlim)

启动仿真
打开vscode或者打包好的exe程序
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260429153052832.png?imageSlim)
只填写图中数据即可

1.选择虚拟串口
2.打开串口
3.连接云端
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260429153249513.png?imageSlim)

此时数据已经上云
打开华为云设备页面
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260429153500503.png?imageSlim)
此时已经有数据

现在下发

![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260429153525609.png?imageSlim)

本地访问这个ip进入web页面
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260429153645465.png?imageSlim)
![image.png](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260429153650893.png?imageSlim)
下载专属app，确保在同一局域网内且本地web服务在运行，扫码可以进入手机页面
（这个app本质上是调用手机webview访问的，本质上还是浏览器）
![50608685c684fce5a49e433b1e4d194a.jpg|400](https://obsidian-picturebed-1256135654.cos.ap-nanjing.myqcloud.com/obsidion/20260429153933367.png?imageSlim)


## 代码
GitHub:https://github.com/ORI2333/stm32-QT-yun-push
如果对你有用或者喜欢，麻烦帮忙给个Star！