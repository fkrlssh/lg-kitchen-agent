'use client';

import { Wrench, X, ChevronRight, Search } from 'lucide-react';

export type ToolCatalogEntry = {
  name: string;
  description: string;
  examples: string[];
};

export type ToolCategory = {
  id: 'info' | 'ui';
  label: string;
  icon: React.ReactNode;
  tools: ToolCatalogEntry[];
};

// 백엔드 backend/src/tools.py 의 CHAT_TOOLS 와 동기. 도구 추가 시 양쪽 모두 수정.
const CATEGORIES: ToolCategory[] = [
  {
    id: 'info',
    label: '정보 조회',
    icon: <Search className="w-3.5 h-3.5" />,
    tools: [
      {
        name: 'get_status',
        description: '제출 현황 — 현재 몇 주차까지 데이터가 있는지, 어느 항목이 미제출인지.',
        examples: ['지금 몇 주차까지 있어?', '미제출 어디야?', '다 냈어?'],
      },
      {
        name: 'get_achievement',
        description: '실적/달성률 — 목표 대비 실적·차이(남은 금액)·달성률. 항목별 조회 가능.',
        examples: ['실적 얼마나 남았어?', '재료비 달성률?', '전체 달성률은?'],
      },
      {
        name: 'get_risks',
        description: '위험/미달 진단 — 목표 미달 영향 큰 항목 + 달성률 최저 항목 top3.',
        examples: ['제일 미달인 항목은?', '위험한 거 뭐야?'],
      },
    ],
  },
  {
    id: 'ui',
    label: 'UI 액션',
    icon: <ChevronRight className="w-3.5 h-3.5" />,
    tools: [
      {
        name: 'navigate',
        description: '페이지 이동 (실적 관리 / 보고서 운영 / 문서 관리 / 제출 관리 / 홈).',
        examples: ['보고서 보여줘', '실적 관리로 가줘'],
      },
      {
        name: 'remind',
        description: '미제출 항목 독촉 안내 — 미제출 목록 + 실적 관리 화면 이동.',
        examples: ['미제출한 데 독촉해줘', '안 낸 데 알려줘'],
      },
    ],
  },
];

export default function ToolCatalog({
  open,
  onClose,
  onSendExample,
}: {
  open: boolean;
  onClose: () => void;
  onSendExample: (message: string) => void;
}) {
  if (!open) return null;

  return (
    <div className="absolute inset-0 z-30 bg-white flex flex-col rounded-2xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 bg-gradient-to-r from-violet-50 to-white flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wrench className="w-4 h-4 text-violet-700" />
          <div>
            <div className="font-semibold text-slate-900 text-sm">도구 카탈로그</div>
            <div className="text-[11px] text-slate-500">챗봇이 사용 가능한 도구</div>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 hover:bg-slate-100 rounded-md text-slate-500"
          aria-label="닫기"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-5">
        {CATEGORIES.map((cat) => (
          <section key={cat.id}>
            <div className="text-[11px] uppercase tracking-wide text-violet-700 font-semibold mb-2 flex items-center gap-1.5">
              {cat.icon}
              {cat.label}
              <span className="text-slate-400 font-normal normal-case">· {cat.tools.length}개</span>
            </div>
            <div className="space-y-2">
              {cat.tools.map((tool) => (
                <div
                  key={tool.name}
                  className="border border-slate-200 rounded-lg p-3 hover:border-violet-300 transition"
                >
                  <div className="flex items-baseline justify-between gap-2 mb-1">
                    <code className="text-[12px] font-mono font-semibold text-violet-700">
                      {tool.name}
                    </code>
                  </div>
                  <p className="text-[12px] text-slate-600 leading-relaxed mb-2">{tool.description}</p>
                  <div className="flex flex-wrap gap-1">
                    {tool.examples.map((ex, i) => (
                      <button
                        key={i}
                        type="button"
                        onClick={() => {
                          onSendExample(ex);
                          onClose();
                        }}
                        className="text-[11px] px-2 py-0.5 bg-slate-50 hover:bg-violet-50 hover:text-violet-700 text-slate-600 border border-slate-200 rounded transition"
                        title="이 명령 보내기"
                      >
                        “{ex}”
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}

        <div className="text-[11px] text-slate-400 border-t border-slate-100 pt-3">
          📝 도구가 더 필요하면 챗에 <code className="text-violet-600">도구 메모: ~~~</code> 입력 →{' '}
          <code className="text-slate-500">backend/tool_wishlist.md</code> 에 저장됩니다.
        </div>
      </div>
    </div>
  );
}
