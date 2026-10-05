import type { Metadata } from "next";
import { notFound } from "next/navigation";
import StockDiscover from "../../../office/StockDiscover";
import { WORKSPACES, isWorkspaceId } from "../../../workspaces";

type Props = { params: Promise<{ workspace: string }> };

/** 이 사무실에 주식 분석 화면(page.href = /<사무실>/stock)을 가진 자동화가 있을 때만 연다 (관심 종목 판과 같은 검사) */
function hasStock(workspace: string): boolean {
  return isWorkspaceId(workspace) && WORKSPACES[workspace].automations.some((a) => a.page?.href === `/${workspace}/stock`);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { workspace } = await params;
  return { title: hasStock(workspace) ? "발굴 — 주식 분석" : "AI 오피스" };
}

export default async function StockDiscoverPage({ params }: Props) {
  const { workspace } = await params;
  if (!hasStock(workspace)) return notFound();
  return <StockDiscover ws={workspace} />;
}
