"use client";
// 사무실 선택 → 엔진 모듈을 그 뒤에 불러온다. 엔진은 모듈을 읽는 시점에 company.config.ts 를 통해
// 현재 사무실 값을 고정하므로, 사무실을 바꿀 때는 전체 페이지를 새로 연다(상단 탭은 일반 링크).
import { useEffect, useState, type ComponentType } from "react";

export default function WorkspaceLoader({ workspace }: { workspace: string }) {
  const [App, setApp] = useState<ComponentType | null>(null);

  useEffect(() => {
    (globalThis as { __WORKSPACE__?: string }).__WORKSPACE__ = workspace;
    document.documentElement.dataset.ws = workspace;
    let alive = true;
    import("./OfficeApp").then((mod) => {
      if (alive) setApp(() => mod.default);
    });
    return () => {
      alive = false;
    };
  }, [workspace]);

  if (!App) {
    return (
      <main className="page-shell">
        <div className="wrap">
          <p className="ws-loading">사무실을 불러오는 중…</p>
        </div>
      </main>
    );
  }
  return <App />;
}
