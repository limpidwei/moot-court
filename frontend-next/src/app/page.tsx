"use client";

import { useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import {
  getCases,
  deleteCase,
  renameCase,
  createShare,
  getNotifications,
  markNotificationRead,
  markAllNotificationsRead,
  type CaseSummary,
  type NotificationItem,
} from "@/lib/api";

const PHASE_LABELS: Record<number, string> = {
  0: "未开始",
  1: "请求权基础分析",
  2: "起诉状与证据目录",
  3: "答辩策略分析",
  4: "答辩状与证据目录",
  5: "争议焦点归纳",
  6: "法庭辩论",
  7: "双方最后陈述",
  8: "判决与胜率评估",
};

function formatDate(iso: string) {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function modeLabel(c: CaseSummary): string {
  if (c.mode === "asymmetric") {
    const side = c.user_side === "plaintiff" ? "原告" : c.user_side === "defendant" ? "被告" : "";
    return `⚔️ 单方对抗${side ? " · " + side : ""}`;
  }
  return "⚖️ 中立观察";
}

export default function HomePage() {
  const router = useRouter();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize] = useState(10);

  // 搜索与过滤
  const [searchQuery, setSearchQuery] = useState("");
  const [filterMode, setFilterMode] = useState("");
  const [filterPhase, setFilterPhase] = useState<number>(-1);
  const [sortBy, setSortBy] = useState("created_at_desc");

  const [expandedCaseId, setExpandedCaseId] = useState<string | null>(null);
  const [editingCaseId, setEditingCaseId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // 通知
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [showNotifs, setShowNotifs] = useState(false);

  // 分享
  const [shareLoading, setShareLoading] = useState<string | null>(null);

  const loadCases = () => {
    setLoading(true);
    getCases({
      q: searchQuery,
      mode: filterMode,
      phase: filterPhase,
      sort: sortBy,
      page: currentPage,
      page_size: pageSize,
    })
      .then((res) => {
        setCases(res.items);
        setTotal(res.total);
      })
      .catch(() => {
        setCases([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  };

  // 加载通知
  const loadNotifications = () => {
    getNotifications()
      .then((res) => {
        setNotifications(res.items);
        setUnreadCount(res.unread_count);
      })
      .catch(() => {});
  };

  // 分享案件
  const handleShare = async (caseId: string, caseTitle: string) => {
    setShareLoading(caseId);
    try {
      const result = await createShare(caseId);
      const fullUrl = `${window.location.origin}${result.url}`;
      await navigator.clipboard.writeText(fullUrl);
      alert(`分享链接已复制到剪贴板：\n${fullUrl}`);
    } catch {
      alert("创建分享链接失败");
    } finally {
      setShareLoading(null);
    }
  };

  // 首次加载
  useEffect(() => {
    loadCases();
    loadNotifications();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 搜索条件变化时重置到第1页并加载
  useEffect(() => {
    setCurrentPage(1);
    loadCases();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, filterMode, filterPhase, sortBy]);

  // 分页变化时加载
  useEffect(() => {
    loadCases();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage]);

  const handleDelete = async (caseId: string, caseTitle: string) => {
    if (
      !confirm(
        `确定要删除案件【${caseTitle || "未命名案件"}】吗？\n删除后无法恢复。`
      )
    )
      return;
    setActionLoading(caseId);
    try {
      await deleteCase(caseId);
      setCases((prev) => prev.filter((c) => c.case_id !== caseId));
      if (expandedCaseId === caseId) setExpandedCaseId(null);
      if (editingCaseId === caseId) setEditingCaseId(null);
      setTotal((t) => Math.max(0, t - 1));
    } catch {
      alert("删除失败");
    } finally {
      setActionLoading(null);
    }
  };

  const startRename = (c: CaseSummary) => {
    setEditingCaseId(c.case_id);
    setEditTitle(c.case_title || "");
  };

  const cancelRename = () => {
    setEditingCaseId(null);
    setEditTitle("");
  };

  const confirmRename = async (caseId: string) => {
    const trimmed = editTitle.trim();
    if (!trimmed) {
      alert("案件名称不能为空");
      return;
    }
    setActionLoading(caseId);
    try {
      await renameCase(caseId, trimmed);
      setCases((prev) =>
        prev.map((c) =>
          c.case_id === caseId ? { ...c, case_title: trimmed } : c
        )
      );
      setEditingCaseId(null);
      setEditTitle("");
    } catch {
      alert("重命名失败");
    } finally {
      setActionLoading(null);
    }
  };

  const totalPages = Math.ceil(total / pageSize);
  const hasActiveFilters = searchQuery || filterMode || filterPhase >= 0;

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="relative text-center mb-10">
          <div className="absolute right-0 top-0">
            <button
              onClick={() => setShowNotifs(!showNotifs)}
              className="relative p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-full transition"
            >
              🔔
              {unreadCount > 0 && (
                <span className="absolute top-0 right-0 bg-red-500 text-white text-xs font-bold px-1.5 py-0.5 rounded-full">
                  {unreadCount}
                </span>
              )}
            </button>
            {showNotifs && (
              <div className="absolute right-0 top-12 w-80 bg-white border border-gray-200 rounded-xl shadow-lg z-50 text-left">
                <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
                  <span className="font-semibold text-gray-700">通知</span>
                  {unreadCount > 0 && (
                    <button
                      onClick={() => { markAllNotificationsRead().then(loadNotifications); }}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      全部已读
                    </button>
                  )}
                </div>
                <div className="max-h-64 overflow-auto">
                  {notifications.length === 0 && (
                    <div className="px-4 py-6 text-center text-sm text-gray-400">暂无通知</div>
                  )}
                  {notifications.map((n) => (
                    <div
                      key={n.id}
                      className={`px-4 py-3 border-b border-gray-50 hover:bg-gray-50 cursor-pointer ${n.read ? "opacity-60" : ""}`}
                      onClick={() => {
                        if (!n.read) markNotificationRead(n.id).then(loadNotifications);
                      }}
                    >
                      <div className="text-sm font-medium text-gray-800">{n.title}</div>
                      <div className="text-xs text-gray-500 mt-0.5 truncate">{n.message}</div>
                      <div className="text-xs text-gray-400 mt-1">{new Date(n.created_at).toLocaleString("zh-CN")}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="text-5xl mb-3">⚖️</div>
          <h1 className="text-3xl font-bold text-gray-800 mb-2">模拟法庭</h1>
          <p className="text-gray-500 leading-relaxed max-w-lg mx-auto">
            输入案情和证据，AI 法官与双方律师即刻按照
            《中华人民共和国民事诉讼法》程序进行模拟庭审。
          </p>
        </div>

        {/* New case button */}
        <div className="mb-8 flex gap-3">
          <button
            onClick={() => router.push("/case/new")}
            className="flex-1 bg-blue-600 text-white px-8 py-4 rounded-xl text-lg font-semibold
                       hover:bg-blue-700 transition shadow-lg shadow-blue-200"
          >
            📋 新建庭审
          </button>
          <button
            onClick={() => router.push("/usage")}
            className="shrink-0 bg-white text-gray-700 border border-gray-200 px-5 py-4 rounded-xl
                       text-lg font-semibold hover:bg-gray-50 transition"
          >
            📊 用量
          </button>
        </div>

        {/* Search & Filters */}
        <div className="bg-white border border-gray-200 rounded-xl p-4 mb-6">
          {/* Search input */}
          <div className="relative mb-4">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">🔍</span>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索案件标题、事实、证据或诉讼请求..."
              className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-lg text-sm
                         focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400"
            />
          </div>

          {/* Filter row */}
          <div className="flex flex-wrap gap-3">
            <select
              value={filterMode}
              onChange={(e) => setFilterMode(e.target.value)}
              className="px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white
                         focus:outline-none focus:ring-2 focus:ring-blue-300"
            >
              <option value="">全部模式</option>
              <option value="neutral">⚖️ 中立观察</option>
              <option value="asymmetric">⚔️ 单方对抗</option>
            </select>

            <select
              value={filterPhase}
              onChange={(e) => setFilterPhase(Number(e.target.value))}
              className="px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white
                         focus:outline-none focus:ring-2 focus:ring-blue-300"
            >
              <option value={-1}>全部阶段</option>
              {Object.entries(PHASE_LABELS).map(([phase, label]) => (
                <option key={phase} value={Number(phase)}>
                  {label}
                </option>
              ))}
            </select>

            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white
                         focus:outline-none focus:ring-2 focus:ring-blue-300"
            >
              <option value="created_at_desc">最新创建</option>
              <option value="created_at_asc">最早创建</option>
              <option value="title_asc">名称 A-Z</option>
            </select>

            {hasActiveFilters && (
              <button
                onClick={() => {
                  setSearchQuery("");
                  setFilterMode("");
                  setFilterPhase(-1);
                  setSortBy("created_at_desc");
                }}
                className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700
                           border border-gray-200 rounded-lg hover:bg-gray-50 transition"
              >
                清除筛选
              </button>
            )}
          </div>
        </div>

        {/* Case list */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-700">
              📂 历史庭审
              {total > 0 && (
                <span className="ml-2 text-sm font-normal text-gray-400">
                  共 {total} 个
                </span>
              )}
            </h2>
          </div>

          {loading && (
            <div className="text-center text-gray-400 py-12">加载中...</div>
          )}

          {!loading && cases.length === 0 && (
            <div className="text-center text-gray-400 py-12 bg-white rounded-xl border border-gray-200">
              <div className="text-3xl mb-2">📝</div>
              <p>{hasActiveFilters ? "未找到符合条件的案件" : "暂无历史庭审"}</p>
              {!hasActiveFilters && (
                <p className="text-sm mt-1">点击上方按钮创建第一个案件</p>
              )}
            </div>
          )}

          <div className="grid gap-4">
            {cases.map((c) => (
              <div
                key={c.case_id}
                className="bg-white border border-gray-200 rounded-xl overflow-hidden hover:shadow-md hover:border-blue-300 transition"
              >
                <button
                  onClick={() =>
                    setExpandedCaseId(
                      expandedCaseId === c.case_id ? null : c.case_id
                    )
                  }
                  className="w-full text-left p-5 flex items-center justify-between"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between mb-2">
                      {editingCaseId === c.case_id ? (
                        <input
                          autoFocus
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") confirmRename(c.case_id);
                            else if (e.key === "Escape") cancelRename();
                          }}
                          placeholder="输入案件名称"
                          className="flex-1 min-w-0 max-w-md px-2 py-1 text-sm font-semibold text-gray-800 border border-blue-400 rounded focus:outline-none focus:ring-2 focus:ring-blue-300"
                        />
                      ) : (
                        <h3 className="font-semibold text-gray-800 truncate pr-4">
                          {c.case_title || "未命名案件"}
                        </h3>
                      )}
                      <span
                        className={`shrink-0 text-xs px-2 py-1 rounded-full font-medium ${
                          c.current_phase === 8
                            ? "bg-green-100 text-green-700"
                            : c.current_phase > 0
                            ? "bg-blue-100 text-blue-700"
                            : "bg-gray-100 text-gray-600"
                        }`}
                      >
                        {PHASE_LABELS[c.current_phase] || "未知"}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-gray-400">
                      <span>创建于 {formatDate(c.created_at)}</span>
                      <span className="text-gray-300">|</span>
                      <span className="text-gray-500">{modeLabel(c)}</span>
                    </div>
                  </div>
                  <span className="text-gray-400 ml-4">
                    {expandedCaseId === c.case_id ? "▲" : "▼"}
                  </span>
                </button>

                {expandedCaseId === c.case_id && (
                  <div className="px-5 pb-5 border-t border-gray-100 pt-3">
                    <p className="text-sm text-gray-600 mb-3">
                      案件编号：
                      <span className="font-mono text-xs">{c.case_id}</span>
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() => router.push(`/workspace/${c.case_id}`)}
                        disabled={actionLoading === c.case_id}
                        className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-indigo-700 transition disabled:opacity-50"
                      >
                        🧭 工作台
                      </button>
                      <button
                        onClick={() => router.push(`/trial/${c.case_id}`)}
                        disabled={actionLoading === c.case_id}
                        className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-blue-700 transition disabled:opacity-50"
                      >
                        进入庭审
                      </button>

                      {editingCaseId === c.case_id ? (
                        <>
                          <button
                            onClick={() => confirmRename(c.case_id)}
                            disabled={actionLoading === c.case_id}
                            className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-green-700 transition disabled:opacity-50"
                          >
                            保存
                          </button>
                          <button
                            onClick={cancelRename}
                            disabled={actionLoading === c.case_id}
                            className="bg-gray-200 text-gray-700 px-4 py-2 rounded-lg text-sm font-semibold hover:bg-gray-300 transition disabled:opacity-50"
                          >
                            取消
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => startRename(c)}
                          disabled={actionLoading === c.case_id}
                          className="bg-gray-100 text-gray-700 px-4 py-2 rounded-lg text-sm font-semibold hover:bg-gray-200 transition disabled:opacity-50"
                        >
                          ✏️ 重命名
                        </button>
                      )}

                      <button
                        onClick={() => handleShare(c.case_id, c.case_title)}
                        disabled={shareLoading === c.case_id}
                        className="bg-green-50 text-green-600 px-4 py-2 rounded-lg text-sm font-semibold hover:bg-green-100 transition disabled:opacity-50"
                      >
                        {shareLoading === c.case_id ? "生成中..." : "🔗 分享"}
                      </button>

                      <button
                        onClick={() =>
                          handleDelete(c.case_id, c.case_title)
                        }
                        disabled={actionLoading === c.case_id}
                        className="bg-red-50 text-red-600 px-4 py-2 rounded-lg text-sm font-semibold hover:bg-red-100 transition disabled:opacity-50 ml-auto"
                      >
                        {actionLoading === c.case_id ? "删除中..." : "🗑️ 删除"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-6">
              <button
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="px-3 py-1 rounded border text-sm disabled:opacity-50"
              >
                上一页
              </button>
              <span className="text-sm text-gray-600">
                第 {currentPage} / {totalPages} 页
              </span>
              <button
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
                className="px-3 py-1 rounded border text-sm disabled:opacity-50"
              >
                下一页
              </button>
            </div>
          )}
        </div>

        {/* Footer features */}
        <div className="mt-12 grid grid-cols-1 sm:grid-cols-3 gap-4 text-center text-sm text-gray-400">
          <div>
            <div className="text-2xl mb-1">📝</div>
            <div>智能录入</div>
            <div className="text-xs">粘贴/上传自动解析</div>
          </div>
          <div>
            <div className="text-2xl mb-1">⚡</div>
            <div>8 阶段庭审</div>
            <div className="text-xs">按民诉法程序</div>
          </div>
          <div>
            <div className="text-2xl mb-1">📊</div>
            <div>量化胜率</div>
            <div className="text-xs">四维度加权评估</div>
          </div>
        </div>
      </div>
    </div>
  );
}
