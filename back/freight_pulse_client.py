"""
freight-pulse MCP SSE 客户端
调用 get_spot_rate — 交叉验证 Drewry WCI + Freightos FBX 免费现货运价

MCP SSE 传输协议:
  1. GET /mcp → 获取 endpoint (含 session_id)
  2. POST /messages/?session_id=xxx → 发送 JSON-RPC 请求
  3. SSE 流返回 JSON-RPC 响应
"""
import requests
import json
import time
import threading
import uuid
import queue


class FreightPulseClient:
    """freight-pulse MCP SSE 客户端"""

    BASE_URL = "https://freight-pulse-mcp.vercel.app"
    SSE_PATH = "/mcp"
    TIMEOUT = 25

    def __init__(self):
        self._message_url = None
        self._responses = queue.Queue()
        self._stop = threading.Event()
        self._connected = False
        self._session = requests.Session()
        self._endpoint_event = threading.Event()
        self._endpoint_value = None

    def connect(self):
        """建立 SSE 连接并初始化 MCP 会话"""
        if self._connected:
            return

        print(f"[freight-pulse] Connecting to {self.BASE_URL}{self.SSE_PATH}...")
        sse_resp = self._session.get(
            self.BASE_URL + self.SSE_PATH,
            stream=True,
            timeout=(5, self.TIMEOUT),
            headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"}
        )

        if not sse_resp.ok:
            raise Exception(f"SSE connection failed: HTTP {sse_resp.status_code}")

        self._stop.clear()
        self._endpoint_event.clear()
        self._endpoint_value = None

        # 启动唯一 SSE 消费者线程
        threading.Thread(target=self._consume_sse, args=(sse_resp,), daemon=True).start()

        # 等待 endpoint 事件
        if not self._endpoint_event.wait(timeout=15):
            raise Exception("Timeout waiting for SSE endpoint")

        self._message_url = self.BASE_URL + self._endpoint_value
        print(f"[freight-pulse] Message URL: {self._message_url}")

        # Initialize
        init = self._call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "logistics-optimizer", "version": "1.0"}
        })
        name = init.get("result", {}).get("serverInfo", {}).get("name", "unknown")
        print(f"[freight-pulse] Initialized: {name}")

        self._notify("notifications/initialized", {})
        self._connected = True

    def _consume_sse(self, resp):
        """唯一 SSE 消费者 — 解析 endpoint + 所有后续事件"""
        print("[freight-pulse] SSE consumer started")
        try:
            for line in resp.iter_lines(decode_unicode=True):
                if self._stop.is_set():
                    break
                if not line:
                    continue

                if line.startswith("data:"):
                    data_str = line.split("data:", 1)[1].strip()
                    if data_str:
                        try:
                            self._responses.put(json.loads(data_str))
                        except json.JSONDecodeError:
                            pass

                # 捕获第一个 data 行作为 endpoint（如果还没捕获到）
                if not self._endpoint_value and line.startswith("data:"):
                    val = line.split("data:", 1)[1].strip()
                    if val.startswith("/messages/"):
                        self._endpoint_value = val
                        self._endpoint_event.set()
                        print(f"[freight-pulse] Endpoint: {val}")

            print("[freight-pulse] SSE stream ended")
        except Exception as e:
            if not self._stop.is_set():
                print(f"[freight-pulse] SSE error: {e}")

    def _call(self, method, params, timeout=None):
        """发送 JSON-RPC 请求并等待 SSE 响应"""
        req_id = str(uuid.uuid4())[:8]
        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }
        timeout = timeout or self.TIMEOUT

        try:
            http_resp = self._session.post(
                self._message_url,
                json=msg,
                timeout=timeout,
                headers={"Content-Type": "application/json"}
            )
            if http_resp.status_code in (200, 202):
                if http_resp.status_code == 200 and http_resp.text.strip():
                    data = http_resp.json()
                    if data.get("result") is not None:
                        return data
            else:
                print(f"[freight-pulse] POST {method} -> {http_resp.status_code}")
        except Exception as e:
            print(f"[freight-pulse] POST error: {e}")

        # 等待 SSE 响应
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                msg = self._responses.get(timeout=min(remaining, 3))
                if msg.get("id") == req_id:
                    return msg
            except queue.Empty:
                pass

        raise Exception(f"[freight-pulse] No response for {method}({req_id}) within {timeout}s")

    def _notify(self, method, params):
        try:
            self._session.post(
                self._message_url,
                json={"jsonrpc": "2.0", "method": method, "params": params},
                timeout=10,
                headers={"Content-Type": "application/json"}
            )
        except Exception:
            pass

    def get_spot_rate(self, origin, destination, container_type="40HC"):
        """
        查询现货运价（免费）
        交叉验证 Drewry WCI + Freightos FBX 指数

        :param origin: 起运港 UN/LOCODE，如 "CNSHA"（上海）
        :param destination: 目的港 UN/LOCODE，如 "USLAX"（洛杉矶）
        :param container_type: 箱型 "20GP", "40GP", "40HC"
        :return: spot rate data
        """
        return self._call("tools/call", {
            "name": "get_spot_rate",
            "arguments": {
                "origin": origin,
                "destination": destination,
                "container_type": container_type
            }
        }, timeout=25)

    def list_tools(self):
        return self._call("tools/list", {})

    def disconnect(self):
        self._stop.set()
        self._connected = False
        print("[freight-pulse] Disconnected")


# ===== 测试 =====
if __name__ == "__main__":
    client = FreightPulseClient()
    try:
        client.connect()

        # 列出工具
        print("\n=== Tools ===")
        tools_resp = client.list_tools()
        tools = tools_resp.get("result", {}).get("tools", [])
        for t in tools:
            print(f"  {t['name']}: {t.get('description', '')[:150]}")

        # 测试运价
        print("\n=== Spot Rate: CNSHA -> USLAX (40HC) ===")
        result = client.get_spot_rate("CNSHA", "USLAX", "40HC")
        content = result.get("result", {}).get("content", [])
        for c in content:
            if c.get("type") == "text":
                print(c.get("text", ""))

        # 再测一个航线
        print("\n=== Spot Rate: CNSHA -> NLRTM (40HC) ===")
        result = client.get_spot_rate("CNSHA", "NLRTM", "40HC")
        content = result.get("result", {}).get("content", [])
        for c in content:
            if c.get("type") == "text":
                print(c.get("text", ""))

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.disconnect()
