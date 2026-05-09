"use client";

// 庭审进度条组件

export default function ProgressBar({
  currentPhase,
  phaseLabels,
}: {
  currentPhase: number;
  phaseLabels: Record<number, string>;
}) {
  return (
    <div className="flex items-center gap-1 overflow-x-auto py-3 px-2 bg-gray-50 rounded-lg">
      {Array.from({ length: 8 }, (_, i) => i + 1).map((phase) => {
        const isCompleted = phase < currentPhase;
        const isCurrent = phase === currentPhase;
        const isPending = phase > currentPhase;

        return (
          <div key={phase} className="flex items-center gap-1 flex-shrink-0">
            <div
              className={`flex items-center justify-center w-8 h-8 rounded-full text-xs font-bold
                ${isCompleted ? "bg-green-500 text-white" : ""}
                ${isCurrent ? "bg-blue-600 text-white ring-2 ring-blue-200" : ""}
                ${isPending ? "bg-gray-200 text-gray-400" : ""}
              `}
              title={phaseLabels[phase] || `阶段 ${phase}`}
            >
              {isCompleted ? "✓" : phase}
            </div>
            {phase < 8 && (
              <div
                className={`w-4 h-0.5 ${
                  isCompleted ? "bg-green-400" : "bg-gray-200"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
