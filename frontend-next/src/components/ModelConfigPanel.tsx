"use client";

import { useState, useEffect } from "react";
import { PROVIDER_PRESETS, type LLMConfig } from "@/lib/api";

interface ModelConfigPanelProps {
  value: LLMConfig | null;
  onChange: (config: LLMConfig | null) => void;
}

const STORAGE_KEY = "moot-court-llm-config";

export default function ModelConfigPanel({ value, onChange }: ModelConfigPanelProps) {
  const [provider, setProvider] = useState(value?.provider || "deepseek");
  const [apiKey, setApiKey] = useState(value?.api_key || "");
  const [model, setModel] = useState(value?.model || "");
  const [baseUrl, setBaseUrl] = useState(value?.base_url || "");
  const [showKey, setShowKey] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [enabled, setEnabled] = useState(!!value);

  const preset = PROVIDER_PRESETS[provider];
  const models = preset?.models || [];

  // 初始化或切换平台时自动填充
  useEffect(() => {
    if (!enabled) return;
    const p = PROVIDER_PRESETS[provider];
    if (p) {
      setBaseUrl(p.base_url);
      if (!model || !models.includes(model)) {
        setModel(p.models[0] || "");
      }
    }
  }, [provider, enabled]);

  // 同步到外部
  useEffect(() => {
    if (!enabled) {
      onChange(null);
      return;
    }
    onChange({
      provider,
      base_url: baseUrl,
      api_key: apiKey,
      model,
      temperature: 0.6,
    });
  }, [enabled, provider, baseUrl, apiKey, model]);

  // 从 localStorage 恢复
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const cfg: LLMConfig = JSON.parse(saved);
        setEnabled(true);
        setProvider(cfg.provider);
        setApiKey(cfg.api_key);
        setModel(cfg.model);
        setBaseUrl(cfg.base_url);
        onChange(cfg);
      }
    } catch {
      // ignore
    }
  }, []);

  // 保存到 localStorage
  useEffect(() => {
    if (enabled && apiKey) {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ provider, base_url: baseUrl, api_key: apiKey, model, temperature: 0.6 })
      );
    }
  }, [enabled, provider, baseUrl, apiKey, model]);

  const providerLabels: Record<string, string> = {
    deepseek: "DeepSeek",
    kimi: "Kimi (Moonshot)",
    glm: "智谱 GLM",
    minimax: "MiniMax",
    mimo: "MiMo (小米)",
  };

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 mb-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold text-gray-800">⚙️ 模型配置</h2>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="w-4 h-4"
          />
          <span className={enabled ? "text-gray-700" : "text-gray-400"}>
            使用自定义 API
          </span>
        </label>
      </div>

      {!enabled && (
        <p className="text-sm text-gray-400">
          使用系统默认配置（DeepSeek）。如需使用自己的 API Key，请勾选上方开关。
        </p>
      )}

      {enabled && (
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">
              平台
            </label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg text-sm"
            >
              {Object.entries(providerLabels).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">
              API Key
            </label>
            <div className="flex gap-2">
              <input
                type={showKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="flex-1 px-3 py-2 border rounded-lg text-sm"
              />
              <button
                onClick={() => setShowKey(!showKey)}
                className="px-3 py-2 border rounded-lg text-sm hover:bg-gray-50"
              >
                {showKey ? "隐藏" : "显示"}
              </button>
            </div>
            <p className="text-xs text-gray-400 mt-1">
              API Key 仅保存在浏览器本地，不会上传到服务器持久化存储。
            </p>
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">
              模型
            </label>
            <div className="flex gap-2">
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="flex-1 px-3 py-2 border rounded-lg text-sm"
              >
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
                <option value="__custom__">其他（手动输入）</option>
              </select>
              {model === "__custom__" && (
                <input
                  type="text"
                  value={model === "__custom__" ? "" : model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="输入模型名"
                  className="flex-1 px-3 py-2 border rounded-lg text-sm"
                />
              )}
            </div>
          </div>

          <button
            onClick={() => setAdvanced(!advanced)}
            className="text-xs text-blue-600 hover:underline"
          >
            {advanced ? "收起高级设置" : "高级设置（修改 Base URL）"}
          </button>

          {advanced && (
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">
                Base URL
              </label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg text-sm"
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
