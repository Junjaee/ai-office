import type { Metadata } from "next";
import { notFound } from "next/navigation";
import WorkspaceLoader from "../office/WorkspaceLoader";
import { WORKSPACES, isWorkspaceId } from "../workspaces";

type Props = { params: Promise<{ workspace: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { workspace } = await params;
  if (!isWorkspaceId(workspace)) return { title: "AI 오피스" };
  const c = WORKSPACES[workspace].company;
  return {
    title: c.pageTitle,
    description: c.description,
    openGraph: { title: c.name, description: c.description },
  };
}

export default async function WorkspacePage({ params }: Props) {
  const { workspace } = await params;
  if (!isWorkspaceId(workspace)) notFound();
  return <WorkspaceLoader workspace={workspace} />;
}
