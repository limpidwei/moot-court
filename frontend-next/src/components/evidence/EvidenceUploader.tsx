"use client";

import { useState, useRef, useCallback } from "react";

interface EvidenceUploaderProps {
  caseId: string;
  onUpload: (files: File[], party: string, evidenceType: string) => Promise<void>;
  uploading: boolean;
}

const PARTY_OPTIONS = [
  { value: "plaintiff", label: "🎯 原告方" },
  { value: "defendant", label: "🛡️ 被告方" },
  { value: "third_party", label: "👤 第三方" },
  { value: "unknown", label: "❓ 未知" },
];

const TYPE_OPTIONS = [
  { value: "", label: "自动判断" },
  { value: "书证", label: "📄 书证" },
  { value: "物证", label: "📦 物证" },
  { value: "电子数据", label: "💻 电子数据" },
  { value: "证人证言", label: "🎤 证人证言" },
  { value: "鉴定意见", label: "🔬 鉴定意见" },
  { value: "视听资料", label: "🎬 视听资料" },
];

export default function EvidenceUploader({ onUpload, uploading }: EvidenceUploaderProps) {
  const [dragOver, setDragOver] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [party, setParty] = useState("unknown");
  const [evidenceType, setEvidenceType] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    setSelectedFiles((prev) => [...prev, ...files]);
  }, []);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    setSelectedFiles((prev) => [...prev, ...files]);
  }, []);

  const handleUpload = async () => {
    if (selectedFiles.length === 0) return;
    await onUpload(selectedFiles, party, evidenceType);
    setSelectedFiles([]);
  };

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  return (
    <div className="bg-white border rounded-xl p-6 shadow-sm">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">📤 上传证据</h3>

      {/* 归属和类型选择 */}
      <div className="flex gap-4 mb-4">
        <div className="flex-1">
          <label className="block text-sm font-medium text-gray-600 mb-1">证据归属</label>
          <select
            value={party}
            onChange={(e) => setParty(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm"
          >
            {PARTY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label className="block text-sm font-medium text-gray-600 mb-1">证据类型</label>
          <select
            value={evidenceType}
            onChange={(e) => setEvidenceType(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm"
          >
            {TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* 拖拽区域 */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`
          border-2 border-dashed rounded-xl p-8 text-center cursor-pointer
          transition-colors
          ${dragOver ? "border-blue-400 bg-blue-50" : "border-gray-300 hover:border-gray-400"}
        `}
      >
        <div className="text-4xl mb-2">📁</div>
        <p className="text-sm text-gray-600">拖拽文件到此处，或点击选择文件</p>
        <p className="text-xs text-gray-400 mt-1">支持 txt, docx, pdf, jpg, png</p>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".txt,.docx,.pdf,.jpg,.jpeg,.png"
          onChange={handleFileSelect}
          className="hidden"
        />
      </div>

      {/* 已选文件列表 */}
      {selectedFiles.length > 0 && (
        <div className="mt-4 space-y-2">
          <p className="text-sm font-medium text-gray-700">
            已选择 {selectedFiles.length} 个文件
          </p>
          {selectedFiles.map((file, idx) => (
            <div
              key={idx}
              className="flex items-center justify-between bg-gray-50 px-3 py-2 rounded-lg text-sm"
            >
              <span className="truncate flex-1">{file.name}</span>
              <span className="text-xs text-gray-400 mx-2">
                {(file.size / 1024).toFixed(1)} KB
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  removeFile(idx);
                }}
                className="text-red-500 hover:text-red-700 text-xs"
              >
                ✕
              </button>
            </div>
          ))}
          <button
            onClick={handleUpload}
            disabled={uploading}
            className="w-full bg-blue-600 text-white py-2.5 rounded-lg text-sm font-semibold
                       disabled:opacity-50 hover:bg-blue-700 transition"
          >
            {uploading ? "上传解析中..." : `上传 ${selectedFiles.length} 个文件`}
          </button>
        </div>
      )}
    </div>
  );
}
