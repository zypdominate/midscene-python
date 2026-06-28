/**
 * midscene-web Node.js RPC Service
 *
 * 作为 Python 侧 MidsceneWebAgent 的后端，通过 JSON-RPC 2.0 over HTTP 通信。
 * 由 Python 的 NodeServiceManager 启动，进程级单例，支持多 session 并发。
 *
 * createSession 按 driver 分支：
 *   - puppeteer（默认）：puppeteer.launch 或 puppeteer.connect({browserURL}) → PuppeteerAgent(page)
 *   - playwright / bridge：占位，暂未实现。
 **/

'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');

const sessions = new Map();
let sessionCounter = 0;

let SERVICE_VERSION = 'unknown';
try {
    SERVICE_VERSION = require('./package.json').version || 'unknown';
} catch (_) {
    // package.json 缺失时回退到 'unknown'
}

// ====================== Logging ======================
const LOG_FILE = path.join(process.cwd(), "midscene_web_service.log");
const LOG_MAX_BYTES = 5 * 1024 * 1024; // 单个日志文件上限 5MB，超过则轮转一份

function rotateLogIfNeeded() {
    try {
        if (fs.statSync(LOG_FILE).size > LOG_MAX_BYTES) {
            fs.renameSync(LOG_FILE, `${LOG_FILE}.1`);
        }
    } catch (_) {
        // 文件不存在或 stat 失败，忽略
    }
}

function log(message) {
    const timestamp = new Date().toLocaleTimeString("en-US", {hour12: false});
    const line = `[${timestamp}] ${message}\n`;
    rotateLogIfNeeded();
    fs.appendFileSync(LOG_FILE, line, "utf-8");
    console.log(line.trim());
}

function nextSessionId() {
    sessionCounter += 1;
    return `session_${Date.now()}_${sessionCounter}`;
}

function getSession(sessionId) {
    const session = sessions.get(sessionId);
    if (!session) {
        throw new Error(`Session not found: ${sessionId}`);
    }
    return session;
}

/**
 * 过滤对象中的 null 和 undefined 值，防止传给 Agent 时触发参数校验错误
 */
function cleanOptions(options) {
    const cleaned = {};
    for (const key in options) {
        if (options[key] !== null && options[key] !== undefined) {
            cleaned[key] = options[key];
        }
    }
    return cleaned;
}

// ─── Puppeteer 驱动 ──────────────────────────────────────────────────────────

async function createPuppeteerSession({url, headless, viewport, cdpEndpoint, aiActionContext}) {
    const puppeteer = require('puppeteer');
    const {PuppeteerAgent} = require('@midscene/web/puppeteer');

    let browser;
    let ownsBrowser = true;
    if (cdpEndpoint) {
        // 连接到已有的浏览器实例（用户自管理生命周期）
        browser = await puppeteer.connect({browserURL: cdpEndpoint});
        ownsBrowser = false;
    } else {
        browser = await puppeteer.launch({
            headless: headless !== false,
            defaultViewport: viewport || null,
            args: ['--no-sandbox', '--disable-setuid-sandbox'],
        });
    }

    const pages = await browser.pages();
    const page = pages.length > 0 ? pages[0] : await browser.newPage();

    if (viewport) {
        await page.setViewport(viewport);
    }
    if (url) {
        await page.goto(url, {waitUntil: 'networkidle0'});
    }

    const agentOptions = aiActionContext ? {aiActionContext} : {};
    const agent = new PuppeteerAgent(page, agentOptions);

    return {browser, page, agent, ownsBrowser, driver: 'puppeteer'};
}

async function createSessionByDriver(params) {
    const driver = params.driver || 'puppeteer';
    if (driver === 'puppeteer') {
        return createPuppeteerSession(params);
    }
    if (driver === 'playwright') {
        throw new Error("Playwright driver is not implemented yet (placeholder).");
    }
    if (driver === 'bridge') {
        throw new Error("Bridge driver is not implemented yet (placeholder).");
    }
    throw new Error(`Unknown web driver: ${driver}`);
}

// ─── RPC Handlers ────────────────────────────────────────────────────────────

const handlers = {
    /**
     * 创建网页会话
     * params: { driver, url, headless, viewport, cdpEndpoint, aiActionContext }
     */
    async createSession(params) {
        const driver = params.driver || 'puppeteer';
        log(`Creating ${driver} session (url=${params.url || '-'})`);
        const session = await createSessionByDriver(params);

        const sessionId = nextSessionId();
        sessions.set(sessionId, session);
        log(`Session created: ${sessionId} (driver: ${driver})`);
        return {sessionId, driver};
    },

    /**
     * 销毁会话，关闭浏览器（connect 模式下不关闭，仅断开）
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
            if (session.ownsBrowser) {
                await session.browser.close?.();
            } else {
                await session.browser.disconnect?.();
            }
        } catch (e) {
            log(`Error closing browser: ${e.message}`);
        }
        sessions.delete(sessionId);
        return {ok: true};
    },

    // ── Auto Planning ───────────────────────────────────────────────────────────

    async aiAct({sessionId, prompt}) {
        await getSession(sessionId).agent.aiAct(prompt);
        return {ok: true};
    },

    // ── Instant Actions ─────────────────────────────────────────────────────────

    async aiTap({sessionId, locate}) {
        await getSession(sessionId).agent.aiTap(locate);
        return {ok: true};
    },

    async aiInput({sessionId, locate, value}) {
        await getSession(sessionId).agent.aiInput(value, locate);
        return {ok: true};
    },

    async aiClearInput({sessionId, locate}) {
        await getSession(sessionId).agent.aiClearInput?.(locate);
        return {ok: true};
    },

    async aiScroll({sessionId, locate, direction, scrollType, distance}) {
        const options = cleanOptions({scrollType, distance});
        if (direction) {
            options.direction = direction;
        }
        await getSession(sessionId).agent.aiScroll(options, locate);
        return {ok: true};
    },

    async aiHover({sessionId, locate}) {
        await getSession(sessionId).agent.aiHover(locate);
        return {ok: true};
    },

    async aiDoubleClick({sessionId, locate}) {
        await getSession(sessionId).agent.aiDoubleClick?.(locate);
        return {ok: true};
    },

    async aiKeyboardPress({sessionId, locate, keyName}) {
        await getSession(sessionId).agent.aiKeyboardPress(keyName, locate);
        return {ok: true};
    },

    async aiAsk({sessionId, prompt}) {
        const data = await getSession(sessionId).agent.aiAsk(prompt);
        return {data};
    },

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

    // ── Page navigation (web-specific) ───────────────────────────────────────────

    async goto({sessionId, url}) {
        await getSession(sessionId).page.goto(url, {waitUntil: 'networkidle0'});
        return {ok: true};
    },

    async setViewport({sessionId, width, height}) {
        await getSession(sessionId).page.setViewport({width, height});
        return {ok: true};
    },

    async newTab({sessionId, url}) {
        const session = getSession(sessionId);
        const {PuppeteerAgent} = require('@midscene/web/puppeteer');
        const page = await session.browser.newPage();
        if (url) {
            await page.goto(url, {waitUntil: 'networkidle0'});
        }
        session.page = page;
        session.agent = new PuppeteerAgent(page);
        return {ok: true};
    },

    // ── Shared helpers ────────────────────────────────────────────────────────────

    async getScreenshot({sessionId}) {
        const base64 = await getSession(sessionId).page.screenshot({encoding: 'base64'});
        return {screenshot: base64};
    },

    setAIActContext({sessionId, aiActionContext}) {
        getSession(sessionId).agent.setAIActContext?.(aiActionContext);
        return {ok: true};
    },

    async runYaml({sessionId, yamlContent}) {
        const result = await getSession(sessionId).agent.runYaml(yamlContent);
        return {result};
    },

    getReportFile({sessionId}) {
        const reportPath = getSession(sessionId).agent.reportFile;
        return {reportPath: reportPath || null};
    },

    getStatus({sessionId}) {
        const session = getSession(sessionId);
        return {
            status: "connected",
            driver: session.driver,
            sessionId: sessionId
        };
    },

    ping() {
        return {
            pong: true,
            pid: process.pid,
            version: SERVICE_VERSION,
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
