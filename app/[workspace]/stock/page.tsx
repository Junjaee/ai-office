import type { Metadata } from "next";
import { notFound } from "next/navigation";
import StockBoard from "../../office/StockBoard";
import { WORKSPACES, isWorkspaceId } from "../../workspaces";

type Props = { params: Promise<{ workspace: string }> };

/** 이 사무실에 주식 분석 화면(page.href = /<사무실>/stock)을 가진 자동화가 있을 때만 연다 */
function hasStock(workspace: string): boolean {
  return isWorkspaceId(workspace) && WORKSPACES[workspace].automations.some((a) => a.page?.href === `/${workspace}/stock`);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { workspace } = await params;
  return { title: hasStock(workspace) ? `주식 분석 — ${WORKSPACES[workspace].company.name}` : "AI 오피스" };
}

export default async function StockBoardPage({ params }: Props) {
  const { workspace } = await params;
  if (!hasStock(workspace)) return notFound();
  return <StockBoard ws={workspace} />;
}
