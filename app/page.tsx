import { redirect } from "next/navigation";
import { DEFAULT_WORKSPACE } from "./workspaces";

/** 루트는 기본 사무실로 보낸다 */
export default function RootPage() {
  redirect(`/${DEFAULT_WORKSPACE}`);
}
