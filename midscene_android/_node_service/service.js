/**
 * midscene-android Node.js RPC Service
 *
 * 作为 Python 侧 MidsceneAgent 的后端，通过 JSON-RPC 2.0 over HTTP 通信。
 * 由 Python 的 NodeServiceManager 启动，进程级单例，支持多 session 并发。
 *
 * 环境变量（由 Python 侧注入）：
 *   PORT                      - 监听端口（必须）
 *   MIDSCENE_MODEL_BASE_URL   - AI 模型 base URL
 *   MIDSCENE_MODEL_API_KEY    - AI 模型 API Key（已解码）
 *   MIDSCENE_MODEL_NAME       - 模型名称
 *   MIDSCENE_MODEL_FAMILY     - 模型家族（openai/qwen/doubao 等）
 */

'use strict';

const http = require('http');
const { AndroidAgent, AndroidDevice } = require('@midscene/android');

// ─── Session 管理 ────────────────────────────────────────────────────────────

/** @type {Map<string, { device: AndroidDevice, agent: AndroidAgent }>} */
const sessions = new Map();

let sessionCounter = 0;

function generateSessionId() {
  return `session_${Date.now()}_${++sessionCounter}`;
}

// ─── RPC Handlers ────────────────────────────────────────────────────────────

const handlers = {
  /**
   * 创建设备会话，对应 JS 侧 new AndroidDevice() + new AndroidAgent()
   * params: { deviceId, agentOptions? }
   * agentOptions 透传给 AndroidAgent 构造函数（generateReport 等）
   */
  async createSession({ deviceId, deviceOptions = {}, agentOptions = {} }) {
    const device = new AndroidDevice(deviceId, {
      autoDismissKeyboard: deviceOptions.autoDismissKeyboard ?? true,
      androidAdbPath: deviceOptions.androidAdbPath,
      remoteAdbHost: deviceOptions.remoteAdbHost,
      remoteAdbPort: deviceOptions.remoteAdbPort,
    });
    await device.connect();

    const agent = new AndroidAgent(device, {
      generateReport: agentOptions.generateReport ?? false,
      autoPrintReportMsg: agentOptions.autoPrintReportMsg ?? false,
      aiActContext: agentOptions.aiActContext,
      waitAfterAction: agentOptions.waitAfterAction,
    });

    const sessionId = generateSessionId();
    sessions.set(sessionId, { device, agent });
    return { sessionId };
  },

  /**
   * 销毁会话，释放设备连接
   */
  async destroySession({ sessionId }) {
    const sess = sessions.get(sessionId);
    if (!sess) return { ok: true };
    try {
      await sess.agent.destroy?.();
      await sess.device.disconnect?.();
    } catch (e) {
      // 忽略断开连接时的错误
    }
    sessions.delete(sessionId);
    return { ok: true };
  },

  // ── Auto Planning ───────────────────────────────────────────────────────────

  /**
   * agent.aiAct() - AI 自动规划并执行
   * params: { sessionId, prompt, options? }
   */
  async aiAct({ sessionId, prompt, options = {} }) {
    const { agent } = _getSession(sessionId);
    await agent.aiAct(prompt, options);
    return { ok: true };
  },

  // ── Instant Actions ─────────────────────────────────────────────────────────

  /**
   * agent.aiTap() - 点击
   * params: { sessionId, locate, options? }
   */
  async aiTap({ sessionId, locate, options = {} }) {
    const { agent } = _getSession(sessionId);
    await agent.aiTap(locate, options);
    return { ok: true };
  },

  /**
   * agent.aiInput() - 输入文本
   * params: { sessionId, locate, text, options? }
   */
  async aiInput({ sessionId, locate, text, options = {} }) {
    const { agent } = _getSession(sessionId);
    await agent.aiInput(locate, text, options);
    return { ok: true };
  },

  /**
   * agent.aiClearInput() - 清空输入框
   * params: { sessionId, locate, options? }
   */
  async aiClearInput({ sessionId, locate, options = {} }) {
    const { agent } = _getSession(sessionId);
    await agent.aiClearInput(locate, options);
    return { ok: true };
  },

  /**
   * agent.aiScroll() - 滚动
   * params: { sessionId, locate, direction, scrollType?, distance?, options? }
   */
  async aiScroll({ sessionId, locate, direction, scrollType, distance, options = {} }) {
    const { agent } = _getSession(sessionId);
    await agent.aiScroll(
      { locate, direction, scrollType, distance },
      options,
    );
    return { ok: true };
  },

  /**
   * agent.aiLongPress() - 长按
   */
  async aiLongPress({ sessionId, locate, options = {} }) {
    const { agent } = _getSession(sessionId);
    await agent.aiLongPress(locate, options);
    return { ok: true };
  },

  /**
   * agent.aiDoubleClick() - 双击
   */
  async aiDoubleClick({ sessionId, locate, options = {} }) {
    const { agent } = _getSession(sessionId);
    await agent.aiDoubleClick(locate, options);
    return { ok: true };
  },

  /**
   * agent.aiKeyboardPress() - 按键
   * params: { sessionId, key }  key: 'Enter'|'Back'|'Home'|...
   */
  async aiKeyboardPress({ sessionId, key, options = {} }) {
    const { agent } = _getSession(sessionId);
    await agent.aiKeyboardPress(key, options);
    return { ok: true };
  },

  // ── Utility ─────────────────────────────────────────────────────────────────

  /**
   * agent.aiAssert() - AI 视觉断言
   * 不抛异常，返回 { pass, reason } 由 Python 侧决定是否 raise
   */
  async aiAssert({ sessionId, assertion, options = {} }) {
    const { agent } = _getSession(sessionId);
    try {
      await agent.aiAssert(assertion, undefined, options);
      return { pass: true, reason: null };
    } catch (e) {
      // aiAssert 失败时抛出，我们捕获并转为结构化结果
      return { pass: false, reason: e.message };
    }
  },

  /**
   * agent.aiQuery() - 结构化数据提取
   * params: { sessionId, schema }
   * schema: Midscene query schema 字符串，如 '{title: string, price: number}[]'
   */
  async aiQuery({ sessionId, schema, options = {} }) {
    const { agent } = _getSession(sessionId);
    const data = await agent.aiQuery(schema, options);
    return { data };
  },

  /**
   * agent.aiWaitFor() - 等待条件满足
   * params: { sessionId, condition, timeoutMs?, checkIntervalMs? }
   */
  async aiWaitFor({ sessionId, condition, timeoutMs = 15000, checkIntervalMs }) {
    const { agent } = _getSession(sessionId);
    const opts = { timeoutMs };
    if (checkIntervalMs !== undefined) opts.checkIntervalMs = checkIntervalMs;
    await agent.aiWaitFor(condition, opts);
    return { ok: true };
  },

  /**
   * AndroidAgent.openUrl() - 打开网页或 App
   * params: { sessionId, uri }
   */
  async openUrl({ sessionId, uri }) {
    const { agent } = _getSession(sessionId);
    await agent.openUrl(uri);
    return { ok: true };
  },

  /**
   * 健康检查，Python 侧启动时轮询此接口确认服务就绪
   */
  ping() {
    return { pong: true, pid: process.pid };
  },
};

// ─── 工具函数 ────────────────────────────────────────────────────────────────

function _getSession(sessionId) {
  const sess = sessions.get(sessionId);
  if (!sess) {
    throw new Error(`Session not found: ${sessionId}`);
  }
  return sess;
}

// ─── HTTP 服务器 ─────────────────────────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  // 只接受 POST /rpc
  if (req.method !== 'POST' || req.url !== '/rpc') {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
    return;
  }

  let body = '';
  try {
    body = await new Promise((resolve, reject) => {
      let chunks = '';
      req.on('data', (chunk) => { chunks += chunk; });
      req.on('end', () => resolve(chunks));
      req.on('error', reject);
    });
  } catch (e) {
    res.writeHead(400);
    res.end(JSON.stringify({ error: 'Failed to read request body' }));
    return;
  }

  let rpcRequest;
  try {
    rpcRequest = JSON.parse(body);
  } catch (e) {
    res.writeHead(400);
    res.end(JSON.stringify({ error: 'Invalid JSON' }));
    return;
  }

  const { jsonrpc, id, method, params = {} } = rpcRequest;
  const handler = handlers[method];

  let rpcResponse;
  if (!handler) {
    rpcResponse = {
      jsonrpc,
      id,
      error: { code: -32601, message: `Method not found: ${method}` },
    };
  } else {
    try {
      const result = await handler(params);
      rpcResponse = { jsonrpc, id, result };
    } catch (e) {
      rpcResponse = {
        jsonrpc,
        id,
        error: { code: -1, message: e.message, stack: e.stack },
      };
    }
  }

  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(rpcResponse));
});

// ─── 启动 ────────────────────────────────────────────────────────────────────

const PORT = parseInt(process.env.PORT || '0', 10);

server.listen(PORT, '127.0.0.1', () => {
  const addr = server.address();
  // 输出实际端口（PORT=0 时由 OS 分配），Python 侧解析此行获取端口
  // 格式固定为 MIDSCENE_SERVICE_READY:{port}，方便 Python 侧用 startswith 解析
  process.stdout.write(`MIDSCENE_SERVICE_READY:${addr.port}\n`);
});

// 优雅退出：清理所有 session
async function gracefulShutdown() {
  const destroyAll = Array.from(sessions.keys()).map((id) =>
    handlers.destroySession({ sessionId: id }).catch(() => {}),
  );
  await Promise.allSettled(destroyAll);
  server.close(() => process.exit(0));
}

process.on('SIGTERM', gracefulShutdown);
process.on('SIGINT', gracefulShutdown);