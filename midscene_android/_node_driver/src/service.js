/**
 * midscene-android Node.js RPC Service
 *
 * 作为 Python 侧 MidsceneAgent 的后端，通过 JSON-RPC 2.0 over HTTP 通信。
 * 由 Python 的 NodeServiceManager 启动，进程级单例，支持多 session 并发。
 **/

'use strict';

const {execFile} = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const {
    AndroidAgent,
    AndroidDevice,
    getConnectedDevices
} = require('@midscene/android');

const sessions = new Map();
let sessionCounter = 0;

// ====================== Logging ======================
const LOG_FILE = path.join(process.cwd(), "midscene_service.log");

function log(message) {
    const timestamp = new Date().toLocaleTimeString("en-US", { hour12: false });
    const line = `[${timestamp}] ${message}\n`;
    fs.appendFileSync(LOG_FILE, line, "utf-8");
    console.log(line.trim());
}

function nextSessionId() {
    sessionCounter += 1;
    return `session_${Date.now()}_${sessionCounter}`;
}

function runCommand(command, args, options = {}) {
    return new Promise((resolve, reject) => {
        execFile(command, args, {...options, windowsHide: true}, (error, stdout, stderr) => {
            if (error) {
                error.stdout = stdout;
                error.stderr = stderr;
                reject(error);
                return;
            }
            resolve(stdout);
        });
    });
}

function getSession(sessionId) {
    const session = sessions.get(sessionId);
    if (!session) {
        throw new Error(`Session not found: ${sessionId}`);
    }
    return session;
}

function parseAdbDevices(stdout) {
    return stdout
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => line && !line.startsWith('List of devices') && !line.startsWith('*'))
        .map((line) => {
            const [udid, state] = line.split(/\s+/);
            return {udid, state};
        })
        .filter((device) => device.udid && device.state);
}

async function listConnectedDevices() {
    try {
        // Method 1: Try manual adb call (most compatible with PATH-only setups)
        const stdout = await runCommand('adb', ['devices'], {timeout: 10000});
        const devices = parseAdbDevices(stdout);
        if (devices.length > 0) {
            return devices;
        }
    } catch (e) {
        log(`Manual adb devices failed: ${e.message}`);
    }

    try {
        // Method 2: Fallback to @midscene/android's internal discovery
        const devices = await getConnectedDevices();
        return devices.map(udid => ({udid, state: 'device'}));
    } catch (error) {
        log(`Internal getConnectedDevices failed: ${error.message}`);
        throw new Error(`Unable to list Android devices. Please ensure 'adb' is in your PATH or ANDROID_HOME is set. Error: ${error.message}`);
    }
}

// ─── RPC Handlers ────────────────────────────────────────────────────────────

const handlers = {
    /**
     * 创建设备会话，对应 JS 侧 new AndroidDevice() + new AndroidAgent()
     * params: { deviceId, aiActionContext }
     */
    async createSession({deviceId, aiActionContext}) {
        let targetDeviceId = deviceId;
        if (!targetDeviceId) {
            const devices = await listConnectedDevices();
            if (devices.length === 0) {
                throw new Error("No connected Android devices found via ADB");
            }
            targetDeviceId = devices[0].udid;
        }

        log(`Creating session for device: ${targetDeviceId}`);
        const device = new AndroidDevice(targetDeviceId);
        await device.connect();
        
        const agentOptions = aiActionContext ? { aiActionContext } : {};
        const agent = new AndroidAgent(device, agentOptions);
        
        const sessionId = nextSessionId();
        sessions.set(sessionId, {device, agent, deviceId: targetDeviceId});
        
        log(`Session created: ${sessionId} (device: ${targetDeviceId})`);
        return {sessionId, deviceId: targetDeviceId};
    },

    /**
     * 销毁会话，释放设备连接
     */
    async destroySession({sessionId}) {
        const session = sessions.get(sessionId);
        if (!session) {
            return {ok: true};
        }
        log(`Destroying session: ${sessionId}`);
        try {
            await session.agent.destroy?.();
        } catch (e) {
            log(`Error destroying agent: ${e.message}`);
        }
        try {
            await session.device.disconnect?.();
        } catch (e) {
            log(`Error disconnecting device: ${e.message}`);
        }
        sessions.delete(sessionId);
        return {ok: true};
    },

    // ── Auto Planning ───────────────────────────────────────────────────────────

    /**
     * agent.aiAct() - AI 自动规划并执行
     * params: { sessionId, prompt }
     */
    async aiAct({sessionId, prompt}) {
        await getSession(sessionId).agent.aiAct(prompt);
        return {ok: true};
    },

    // ── Instant Actions ─────────────────────────────────────────────────────────

    /**
     * agent.aiTap() - 点击
     * params: { sessionId, locate }
     */
    async aiTap({sessionId, locate}) {
        await getSession(sessionId).agent.aiTap(locate);
        return {ok: true};
    },

    /**
     * agent.aiInput() - 输入文本
     * params: { sessionId, locate, value }
     */
    async aiInput({sessionId, locate, value}) {
        await getSession(sessionId).agent.aiInput(locate, {value});
        return {ok: true};
    },

    /**
     * agent.aiClearInput() - 清空输入框
     * params: { sessionId, locate }
     */
    async aiClearInput({sessionId, locate}) {
        await getSession(sessionId).agent.aiClearInput(locate);
        return {ok: true};
    },

    /**
     * agent.aiScroll() - 滚动
     *     * params: { sessionId, locate, direction, scrollType?, distance? }
     */
    async aiScroll({sessionId, locate, direction, scrollType, distance}) {
        const options = {};
        if (direction !== undefined) options.direction = direction;
        if (scrollType !== undefined) options.scrollType = scrollType;
        if (distance !== undefined) options.distance = distance;
        await getSession(sessionId).agent.aiScroll(locate, options);
        return {ok: true};
    },

    async aiPinch({sessionId, locate, direction, distance, duration}) {
        const options = {};
        if (direction !== undefined) options.direction = direction;
        if (distance !== undefined) options.distance = distance;
        if (duration !== undefined) options.duration = duration;
        await getSession(sessionId).agent.aiPinch(locate, options);
        return {ok: true};
    },

    async aiLongPress({sessionId, locate, duration}) {
        const options = duration === undefined ? undefined : {duration};
        await getSession(sessionId).agent.aiLongPress(locate, options);
        return {ok: true};
    },

    async aiDoubleClick({sessionId, locate}) {
        await getSession(sessionId).agent.aiDoubleClick(locate);
        return {ok: true};
    },

    async aiKeyboardPress({sessionId, locate, keyName}) {
        if (locate === undefined || locate === null) {
            await getSession(sessionId).agent.aiKeyboardPress(keyName);
        } else {
            await getSession(sessionId).agent.aiKeyboardPress(locate, {keyName});
        }
        return {ok: true};
    },

    async aiAsk({sessionId, prompt}) {
        const data = await getSession(sessionId).agent.aiAsk(prompt);
        return {data};
    },

    /**
     * agent.aiQuery() - 结构化数据提取
     * params: { sessionId, schema }
     * schema: Midscene query schema 字符串，如 '{title: string, price: number}[]'
     */
    async aiQuery({sessionId, dataDemand}) {
        const data = await getSession(sessionId).agent.aiQuery(dataDemand);
        return {data};
    },

    async aiBoolean({sessionId, prompt}) {
        const data = await getSession(sessionId).agent.aiBoolean(prompt);
        return {data};
    },

    async aiNumber({sessionId, prompt}) {
        const data = await getSession(sessionId).agent.aiNumber(prompt);
        return {data};
    },

    async aiString({sessionId, prompt}) {
        const data = await getSession(sessionId).agent.aiString(prompt);
        return {data};
    },

    async aiLocate({sessionId, locate}) {
        const data = await getSession(sessionId).agent.aiLocate(locate);
        return {data};
    },

    async aiAssert({sessionId, assertion}) {
        try {
            await getSession(sessionId).agent.aiAssert(assertion);
            return {pass: true, reason: null};
        } catch (error) {
            return {pass: false, reason: error.message};
        }
    },

    async aiWaitFor({sessionId, assertion, timeoutMs}) {
        await getSession(sessionId).agent.aiWaitFor(assertion, {timeoutMs});
        return {ok: true};
    },

    // ── Device & System Actions ──────────────────────────────────────────────────

    async back({sessionId}) {
        await getSession(sessionId).device.back();
        return {ok: true};
    },

    async home({sessionId}) {
        await getSession(sessionId).device.home();
        return {ok: true};
    },

    async recentApps({sessionId}) {
        await getSession(sessionId).device.recentApps();
        return {ok: true};
    },

    async launchApp({sessionId, packageName}) {
        await getSession(sessionId).device.launchApp(packageName);
        return {ok: true};
    },

    async terminateApp({sessionId, packageName}) {
        await getSession(sessionId).device.terminateApp(packageName);
        return {ok: true};
    },

    async getScreenshot({sessionId}) {
        const base64 = await getSession(sessionId).device.screenshot();
        return {screenshot: base64};
    },

    // ── Advanced Automation ──────────────────────────────────────────────────────

    async setAIActContext({sessionId, aiActionContext}) {
        getSession(sessionId).agent.setAIActContext(aiActionContext);
        return {ok: true};
    },

    async runYaml({sessionId, yamlContent}) {
        const result = await getSession(sessionId).agent.runYaml(yamlContent);
        return {result};
    },

    async getReportFile({sessionId}) {
        // midscene-android agent usually has a report file path if it's generated
        const reportPath = getSession(sessionId).agent.reportFile;
        return {reportPath: reportPath || null};
    },

    async getStatus({sessionId}) {
        const session = getSession(sessionId);
        return {
            status: "connected",
            deviceId: session.deviceId,
            sessionId: sessionId
        };
    },

    async runAdbShell({sessionId, command, timeoutMs}) {
        const output = await getSession(sessionId).agent.runAdbShell(
            command,
            timeoutMs === undefined ? undefined : {timeout: timeoutMs},
        );
        return {output};
    },

    async getConnectedDevices() {
        return {devices: await listConnectedDevices()};
    },

    ping() {
        return {
            pong: true,
            pid: process.pid,
            version: "0.1.0",
            activeSessions: sessions.size
        };
    },
};

const server = http.createServer(async (req, res) => {
    if (req.method !== 'POST' || req.url !== '/rpc') {
        res.writeHead(404, {'Content-Type': 'application/json'});
        res.end(JSON.stringify({error: 'Not found'}));
        return;
    }

    let body = '';
    try {
        body = await new Promise((resolve, reject) => {
            let chunks = '';
            req.on('data', (chunk) => {
                chunks += chunk;
            });
            req.on('end', () => resolve(chunks));
            req.on('error', reject);
        });
    } catch (_) {
        res.writeHead(400, {'Content-Type': 'application/json'});
        res.end(JSON.stringify({error: 'Failed to read request body'}));
        return;
    }

    let rpcRequest;
    try {
        rpcRequest = JSON.parse(body);
    } catch (_) {
        res.writeHead(400, {'Content-Type': 'application/json'});
        res.end(JSON.stringify({error: 'Invalid JSON'}));
        return;
    }

    const {jsonrpc, id, method, params = {}} = rpcRequest;
    const handler = handlers[method];

    let rpcResponse;
    if (!handler) {
        rpcResponse = {
            jsonrpc,
            id,
            error: {code: -32601, message: `Method not found: ${method}`},
        };
    } else {
        try {
            rpcResponse = {jsonrpc, id, result: await handler(params)};
        } catch (error) {
            rpcResponse = {
                jsonrpc,
                id,
                error: {code: -1, message: error.message, stack: error.stack},
            };
        }
    }

    res.writeHead(200, {'Content-Type': 'application/json'});
    res.end(JSON.stringify(rpcResponse));
});

const PORT = parseInt(process.env.PORT || '0', 10);

server.listen(PORT, '127.0.0.1', () => {
    const addr = server.address();
    const message = `MIDSCENE_SERVICE_READY:${addr.port}`;
    log(`Service started on port ${addr.port} (PID: ${process.pid})`);
    log(`Environment: PATH=${process.env.PATH}`);
    log(`Environment: ANDROID_HOME=${process.env.ANDROID_HOME}`);
    process.stdout.write(`${message}\n`);
});

async function gracefulShutdown() {
    const tasks = Array.from(sessions.keys()).map((sessionId) =>
        handlers.destroySession({sessionId}).catch(() => {
        }),
    );
    await Promise.allSettled(tasks);
    server.close(() => process.exit(0));
}

process.on('SIGTERM', gracefulShutdown);
process.on('SIGINT', gracefulShutdown);
