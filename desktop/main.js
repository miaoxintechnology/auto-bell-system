const {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  nativeTheme,
  screen,
} = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const net = require("net");
const { spawn } = require("child_process");

const APP_NAME = "自动铃声系统";
const APP_VERSION = "1.0.0";
const DEFAULT_WIDTH = 1200;
const DEFAULT_HEIGHT = 760;

let mainWindow = null;
let splashWindow = null;
let backendProcess = null;
let backendPort = null;
let backendLog = null;
let quitting = false;
let backendKilled = false;
let stateSaveTimer = null;

// 本应用只加载本机自带页面；在部分受限桌面环境中 Chromium 沙箱
// 会导致进程无法启动，因此显式关闭渲染沙箱。
app.commandLine.appendSwitch("no-sandbox");
app.setAppUserModelId("AutoBell.System.Desktop");
function canWriteDirectory(directory) {
  try {
    fs.mkdirSync(directory, { recursive: true });
    const probe = path.join(directory, ".write-probe");
    fs.writeFileSync(probe, "ok", "utf8");
    fs.unlinkSync(probe);
    return true;
  } catch (_error) {
    return false;
  }
}

function chooseUserData() {
  const override = process.env.AUTOBELL_ELECTRON_DATA;
  if (override) {
    const resolved = path.resolve(override);
    if (canWriteDirectory(resolved)) return resolved;
  }
  const candidates = [
    // 便携/安装目录优先，便于整个目录迁移，也避免部分安全软件
    // 对 Electron 写入用户 AppData 的拦截。
    path.join(path.dirname(process.execPath), "AutoBellData"),
    path.join(
      process.env.LOCALAPPDATA || app.getPath("appData"),
      "AutoBellDesktop",
    ),
    path.join(app.getPath("temp"), "AutoBellDesktop"),
  ];
  for (const candidate of candidates) {
    if (canWriteDirectory(candidate)) return candidate;
  }
  return candidates[0];
}

app.setPath("userData", chooseUserData());
fs.mkdirSync(app.getPath("userData"), { recursive: true });

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function log(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  try {
    const logDir = path.join(app.getPath("userData"), "logs");
    ensureDir(logDir);
    fs.appendFileSync(path.join(logDir, "desktop.log"), line, "utf8");
  } catch (_error) {
    // 忽略日志失败
  }
  if (!app.isPackaged) process.stdout.write(line);
}

function windowStateFile() {
  return path.join(app.getPath("userData"), "window-state.json");
}

function loadWindowState() {
  try {
    const raw = JSON.parse(fs.readFileSync(windowStateFile(), "utf8"));
    if (
      Number.isFinite(raw.width) &&
      Number.isFinite(raw.height) &&
      raw.width >= 1000 &&
      raw.height >= 640
    ) {
      const displays = screen.getAllDisplays();
      const visible = displays.some((display) => {
        const area = display.workArea;
        const x = Number(raw.x);
        const y = Number(raw.y);
        return (
          Number.isFinite(x) &&
          Number.isFinite(y) &&
          x + 120 > area.x &&
          y + 60 > area.y &&
          x < area.x + area.width - 120 &&
          y < area.y + area.height - 60
        );
      });
      return {
        width: Math.round(raw.width),
        height: Math.round(raw.height),
        x: visible ? Math.round(raw.x) : undefined,
        y: visible ? Math.round(raw.y) : undefined,
        maximized: Boolean(raw.maximized),
      };
    }
  } catch (_error) {
    // 首次启动
  }
  return {
    width: DEFAULT_WIDTH,
    height: DEFAULT_HEIGHT,
    maximized: false,
  };
}

function saveWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const bounds = mainWindow.getNormalBounds();
  try {
    fs.writeFileSync(
      windowStateFile(),
      JSON.stringify({
        ...bounds,
        maximized: mainWindow.isMaximized(),
      }),
      "utf8",
    );
  } catch (error) {
    log(`保存窗口状态失败：${error.message}`);
  }
}

function scheduleStateSave() {
  clearTimeout(stateSaveTimer);
  stateSaveTimer = setTimeout(saveWindowState, 350);
}

function backendExecutable() {
  if (process.env.AUTOBELL_BACKEND_EXE) {
    return process.env.AUTOBELL_BACKEND_EXE;
  }
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "backend", "AutoBellBackend.exe");
  }
  return path.join(
    __dirname,
    "..",
    "backend-dist",
    "AutoBellBackend",
    "AutoBellBackend.exe",
  );
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = address.port;
      server.close(() => resolve(port));
    });
  });
}

function waitForHealth(port, timeoutMs = 30000) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const request = http.get(
        { host: "127.0.0.1", port, path: "/api/health", timeout: 900 },
        (response) => {
          response.resume();
          if (response.statusCode === 200) {
            resolve();
          } else {
            retry();
          }
        },
      );
      request.on("timeout", () => request.destroy());
      request.on("error", retry);
    };
    const retry = () => {
      if (Date.now() - startedAt > timeoutMs) {
        reject(new Error("后端服务启动超时"));
      } else {
        setTimeout(attempt, 250);
      }
    };
    attempt();
  });
}

function startBackend(port) {
  const executable = backendExecutable();
  const logDir = path.join(app.getPath("userData"), "logs");
  ensureDir(logDir);
  const dataDir = path.join(app.getPath("userData"), "data");
  ensureDir(dataDir);
  backendLog = fs.createWriteStream(path.join(logDir, "backend.log"), {
    flags: "a",
  });
  let command;
  let args;
  let cwd;
  if (fs.existsSync(executable)) {
    command = executable;
    args = ["--host", "127.0.0.1", "--port", String(port)];
    cwd = path.dirname(executable);
  } else if (!app.isPackaged) {
    const script = path.join(__dirname, "..", "backend_entry.py");
    if (!fs.existsSync(script)) {
      throw new Error(`找不到后端程序：${executable}`);
    }
    command = process.env.AUTOBELL_PYTHON || "python";
    args = [script, "--host", "127.0.0.1", "--port", String(port)];
    cwd = path.join(__dirname, "..");
  } else {
    throw new Error(`找不到后端程序：${executable}`);
  }
  log(`启动后端：${command} ${args.join(" ")}`);
  backendProcess = spawn(command, args, {
    cwd,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, AUTOBELL_DATA_DIR: dataDir },
  });
  backendProcess.stdout.pipe(backendLog, { end: false });
  backendProcess.stderr.pipe(backendLog, { end: false });
  backendProcess.on("error", (error) => {
    log(`后端进程错误：${error.message}`);
  });
  backendProcess.on("exit", (code, signal) => {
    log(`后端进程退出：code=${code} signal=${signal}`);
    if (!quitting && !backendKilled) {
      dialog.showErrorBox(
        APP_NAME,
        `铃声后端意外退出（代码 ${code ?? "未知"}）。\n请重新启动程序。`,
      );
      app.quit();
    }
  });
}

function killBackend() {
  if (!backendProcess || backendKilled) return;
  backendKilled = true;
  log("停止后端进程");
  try {
    if (process.platform === "win32" && backendProcess.pid) {
      spawn(
        "taskkill",
        ["/pid", String(backendProcess.pid), "/T", "/F"],
        { windowsHide: true, stdio: "ignore" },
      );
    } else {
      backendProcess.kill();
    }
  } catch (_error) {
    try {
      backendProcess.kill();
    } catch (_ignored) {
      // 忽略
    }
  }
  if (backendLog) {
    try {
      backendLog.end();
    } catch (_error) {
      // 忽略
    }
  }
}

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 380,
    height: 196,
    frame: false,
    transparent: false,
    backgroundColor: "#f3f4f6",
    resizable: false,
    movable: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    show: false,
    hasShadow: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  splashWindow.loadFile(path.join(__dirname, "splash.html"));
  splashWindow.once("ready-to-show", () => splashWindow.show());
}

function createMainWindow(port) {
  const state = loadWindowState();
  mainWindow = new BrowserWindow({
    width: state.width,
    height: state.height,
    x: state.x,
    y: state.y,
    minWidth: 1000,
    minHeight: 640,
    frame: false,
    transparent: false,
    backgroundColor: "#f3f4f6",
    roundedCorners: true,
    hasShadow: true,
    resizable: true,
    maximizable: true,
    minimizable: true,
    show: false,
    title: APP_NAME,
    icon: path.join(__dirname, "assets", "app.ico"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      spellcheck: false,
    },
  });
  mainWindow.setMenuBarVisibility(false);
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(`http://127.0.0.1:${port}`)) {
      event.preventDefault();
    }
  });
  mainWindow.on("maximize", () => {
    mainWindow.webContents.send("window:maximized", true);
    scheduleStateSave();
  });
  mainWindow.on("unmaximize", () => {
    mainWindow.webContents.send("window:maximized", false);
    scheduleStateSave();
  });
  mainWindow.on("resize", scheduleStateSave);
  mainWindow.on("move", scheduleStateSave);
  mainWindow.on("close", () => {
    saveWindowState();
    quitting = true;
    killBackend();
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  mainWindow.loadURL(`http://127.0.0.1:${port}/`);
  mainWindow.once("ready-to-show", () => {
    if (state.maximized) mainWindow.maximize();
    mainWindow.show();
    mainWindow.focus();
  });
  if (app.isPackaged) {
    mainWindow.webContents.on("before-input-event", (event, input) => {
      const devTools =
        input.key === "F12" ||
        (input.control && input.shift && input.key.toLowerCase() === "i");
      if (devTools) event.preventDefault();
    });
  }
}

function registerIpc() {
  ipcMain.on("window:minimize", () => {
    if (mainWindow) mainWindow.minimize();
  });
  ipcMain.on("window:close", () => {
    if (mainWindow) mainWindow.close();
  });
  ipcMain.handle("window:toggle-maximize", () => {
    if (!mainWindow) return false;
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
    return mainWindow.isMaximized();
  });
  ipcMain.handle("window:is-maximized", () => {
    return Boolean(mainWindow && mainWindow.isMaximized());
  });
}

async function bootstrap() {
  nativeTheme.themeSource = "light";
  Menu.setApplicationMenu(null);
  registerIpc();
  createSplash();
  try {
    backendPort = await findFreePort();
    startBackend(backendPort);
    await waitForHealth(backendPort);
    log(`后端就绪：http://127.0.0.1:${backendPort}`);
    createMainWindow(backendPort);
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.close();
      splashWindow = null;
    }
  } catch (error) {
    log(`启动失败：${error.stack || error.message}`);
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
    dialog.showErrorBox(
      APP_NAME,
      `程序启动失败：${error.message}\n\n日志位置：${path.join(
        app.getPath("userData"),
        "logs",
      )}`,
    );
    app.quit();
  }
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  app.whenReady().then(bootstrap);
  app.on("before-quit", () => {
    quitting = true;
    killBackend();
  });
  app.on("window-all-closed", () => {
    app.quit();
  });
}
