import type { Metadata } from "next";
import { notFound } from "next/navigation";
import FlowBoard from "../../office/FlowBoard";
import { WORKSPACES, isWorkspaceId } from "../../workspaces";

type Props = { params: Promise<{ workspace: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { workspace } = await params;
  return { title: isWorkspaceId(workspace) ? `흐름 — ${WORKSPACES[workspace].company.name}` : "AI 오피스" };
}

export default async function FlowPage({ params }: Props) {
  const { workspace } = await params;
  if (!isWorkspaceId(workspace)) notFound();
  return <FlowBoard ws={workspace} />;
}
