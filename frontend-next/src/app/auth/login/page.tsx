"use client";

import { useState, FormEvent, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { setToken, setUser, isAuthenticated } from "@/lib/auth";
import { API_BASE } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [backendStatus, setBackendStatus] = useState<"checking" | "ok" | "error">("checking");
  const [backendDiag, setBackendDiag] = useState("");

  useEffect(() => {
    if (isAuthenticated()) {
      router.push("/");
      return;
    }

    // 后端健康检查（带重试）
    // 首次请求前给浏览器 300ms 完成页面初始化（避免连接池未就绪导致的假性失败）
    let cancelled = false;
    const maxRetries = 8;
    const baseDelayMs = 800;

    async function checkBackend() {
      // 首次尝试前的静默等待，避免页面刚挂载就发请求
      await new Promise((r) => setTimeout(r, 300));
      for (let attempt = 0; attempt < maxRetries; attempt++) {
        if (cancelled) return;
        try {
          const res = await fetch(`${API_BASE}/health`, { method: "GET" });
          if (res.ok) {
            if (!cancelled) {
              setBackendStatus("ok");
              setBackendDiag("");
            }
            return;
          }
          // 非 2xx 响应视为后端未就绪
          if (!cancelled) {
            setBackendStatus("error");
            setBackendDiag(`后端返回 HTTP ${res.status}，正在重试 (${attempt + 1}/${maxRetries})...`);
          }
        } catch (err: any) {
          if (!cancelled) {
            setBackendStatus("error");
            setBackendDiag(
              `正在连接后端 (${attempt + 1}/${maxRetries})... ${err.message || "请稍候"}`
            );
          }
        }
        // 指数退避：800ms, 1.6s, 3.2s, 6.4s...
        await new Promise((r) => setTimeout(r, baseDelayMs * Math.pow(2, attempt)));
      }
      // 全部重试失败
      if (!cancelled) {
        setBackendStatus("error");
        setBackendDiag("后端连接失败，请确认 uvicorn 已启动后点击下方重试按钮");
      }
    }

    checkBackend();
    return () => { cancelled = true; };
  }, [router]);

  function retryHealthCheck() {
    setBackendStatus("checking");
    setBackendDiag("");
    // 简单的单次重试：如果后端已就绪，一次 fetch 就能确认
    let cancelled = false;
    fetch(`${API_BASE}/health`, { method: "GET" })
      .then((res) => {
        if (cancelled) return;
        if (res.ok) { setBackendStatus("ok"); setBackendDiag(""); }
        else { setBackendStatus("error"); setBackendDiag(`后端返回 HTTP ${res.status}`); }
      })
      .catch((err) => {
        if (cancelled) return;
        setBackendStatus("error");
        setBackendDiag(`无法连接: ${err.message || "请确认后端已启动"}`);
      });
    return () => { cancelled = true; };
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      const data = await res.json();

      if (!res.ok) {
        const detail = data.detail;
        const msg = typeof detail === "string" ? detail : JSON.stringify(detail || data);
        throw new Error(msg || "登录失败");
      }

      // 保存 token 和用户信息
      setToken(data.access_token);
      setUser(data.user);

      // 跳转到首页
      router.push("/");
    } catch (err: any) {
      setError(err.message || "登录失败，请重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">
            登录模拟法庭
          </h2>
          <p className="mt-2 text-center text-sm text-gray-600">
            或{" "}
            <Link
              href="/auth/register"
              className="font-medium text-indigo-600 hover:text-indigo-500"
            >
              注册新账号
            </Link>
          </p>

          {backendStatus === "checking" && (
            <p className="mt-2 text-center text-xs text-gray-400 animate-pulse">
              正在连接后端服务...
            </p>
          )}
          {backendStatus === "error" && (
            <div className="mt-3 bg-yellow-50 border border-yellow-200 rounded-md p-3 text-xs text-yellow-800 text-center space-y-2">
              <div>⚠️ {backendDiag.includes("正在") ? backendDiag : "后端连接失败"}</div>
              {backendDiag && !backendDiag.includes("正在") && (
                <div className="text-gray-500">{backendDiag}</div>
              )}
              <button
                type="button"
                onClick={retryHealthCheck}
                className="inline-block mt-1 px-3 py-1 text-xs bg-yellow-200 hover:bg-yellow-300 rounded transition"
              >
                重新连接
              </button>
            </div>
          )}
        </div>
        <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
          <div className="rounded-md shadow-sm -space-y-px">
            <div>
              <label htmlFor="email" className="sr-only">
                邮箱地址
              </label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="appearance-none rounded-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-t-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 focus:z-10 sm:text-sm"
                placeholder="邮箱地址"
              />
            </div>
            <div>
              <label htmlFor="password" className="sr-only">
                密码
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="appearance-none rounded-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-b-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 focus:z-10 sm:text-sm"
                placeholder="密码"
              />
            </div>
          </div>

          {error && (
            <div className="rounded-md bg-red-50 p-4">
              <div className="flex">
                <div className="flex-shrink-0">
                  <svg
                    className="h-5 w-5 text-red-400"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path
                      fillRule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                      clipRule="evenodd"
                    />
                  </svg>
                </div>
                <div className="ml-3">
                  <p className="text-sm text-red-800">{error}</p>
                </div>
              </div>
            </div>
          )}

          <div>
            <button
              type="submit"
              disabled={loading}
              className="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? "登录中..." : "登录"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
