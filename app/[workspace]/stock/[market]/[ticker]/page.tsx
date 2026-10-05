import type { Metadata } from "next";
import { notFound } from "next/navigation";
import StockPage from "../../../../office/StockPage";
import { WORKSPACES, isWorkspaceId } from "../../../../workspaces";

type Props = { params: Promise<{ workspace: string; market: string; ticker: string }> };
const TICKER_RE: Record<string, RegExp> = { us: /^[A-Z][A-Z0-9.\-]{0,9}$/ };

function ok(workspace: string, market: string, ticker: string): boolean {
  return isWorkspaceId(workspace) && WORKSPACES[workspace].automations.some((a) => a.page?.href === `/${workspace}/stock`) && !!TICKER_RE[market]?.test(ticker);
}

/** 깨진 주소(%E0 같은 것)는 URIError 대신 null */
function decode(ticker: string): string | null {
  try {
    return decodeURIComponent(ticker);
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { workspace, market, ticker } = await params;
  const t = decode(ticker);
  return { title: t !== null && ok(workspace, market, t) ? `${t} — 주식 분석` : "AI 오피스" };
}

export default async function StockTickerPage({ params }: Props) {
  const { workspace, market, ticker } = await params;
  const t = decode(ticker);
  if (t === null || !ok(workspace, market, t)) return notFound();
  return <StockPage ws={workspace} market={market} ticker={t} />;
}
