import type { Metadata } from "next";
import { notFound } from "next/navigation";
import LiveBoard from "../../../office/LiveBoard";
import { WORKSPACES, isWorkspaceId } from "../../../workspaces";

type Props = { params: Promise<{ workspace: string; automation: string }> };

function findLive(workspace: string, automation: string) {
  if (!isWorkspaceId(workspace)) return null;
  const def = WORKSPACES[workspace].automations.find((a) => a.id === automation);
  return def?.live ? def : null;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { workspace, automation } = await params;
  const def = findLive(workspace, automation);
  return { title: def ? `${def.live?.title ?? def.name} — ${WORKSPACES[workspace].company.name}` : "AI 오피스" };
}

export default async function LivePage({ params }: Props) {
  const { workspace, automation } = await params;
  const def = findLive(workspace, automation);
  if (!def) return notFound();
  return <LiveBoard ws={workspace} automation={automation} title={def.live?.title ?? def.name} back={`/${workspace}`} />;
}
