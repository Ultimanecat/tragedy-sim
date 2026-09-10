import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

export default async function startServer() {
  const projectRoot = fileURLToPath(new URL("../../", import.meta.url));
  const server = spawn("python", ["-m", "tragedy_sim", "--serve", "--port", "8877"], {
    cwd: projectRoot,
    stdio: "ignore",
    windowsHide: true,
  });
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) throw new Error(`Python 测试服务提前退出：${server.exitCode}`);
    try {
      const response = await fetch("http://127.0.0.1:8877/v1/health");
      if (response.ok) return async () => { server.kill(); };
    } catch { /* Server is still starting. */ }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  server.kill();
  throw new Error("Python 测试服务未能在 10 秒内启动");
}
